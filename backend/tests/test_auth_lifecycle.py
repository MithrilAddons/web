"""Capacity and transaction regressions using temporary databases and fake identities."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mithril_web import auth as auth_module
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY, AuthStore, digest

UUID = "a" * 32
NAME = "SyntheticTest"
ORIGIN = {"Origin": "https://mithril.foo"}


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    app = create_app(
        database=tmp_path / "auth.sqlite3",
        clock=lambda: now[0],
        profile_lookup=lambda *_: {"id": UUID, "name": NAME},
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        yield client, app.state.auth, now


def verify(client):
    challenge = client.post(
        "/api/v1/auth/challenge", json={"version": 1, "uuid": UUID, "name": NAME}
    )
    assert challenge.status_code == 200
    return client.post(
        "/api/v1/auth/verify", json={"challenge_id": challenge.json()["challenge_id"]}
    )


def complete(client, token):
    return client.post(
        "/api/v1/auth/complete", headers=ORIGIN, json={"token": token, "remember": True}
    )


def seed(store, kind, count, *, parent=None, remembered=False):
    with store.db:
        store.db.executemany(
            "INSERT INTO auth VALUES (?,?,?,?,?,?,?)",
            [
                (digest(f"{kind}-{i}"), kind, UUID, NAME, store.clock() + DAY, parent, remembered)
                for i in range(count)
            ],
        )


def count(store, kind):
    return store.db.execute("SELECT COUNT(*) FROM auth WHERE kind=?", (kind,)).fetchone()[0]


def test_confirmed_receipts_do_not_fill_pending_link_capacity(setup):
    client, store, _ = setup
    session = store.issue("session", UUID, NAME, DAY)
    seed(store, "receipt", 1000, parent=digest(session), remembered=True)
    result = verify(client)
    assert result.status_code == 200
    assert complete(client, result.json()["link_token"]).status_code == 200


def test_more_than_1000_live_sync_credentials_can_coexist(setup):
    client, store, _ = setup
    issued = verify(client).json()
    assert complete(client, issued["link_token"]).status_code == 200
    session = client.cookies.get(COOKIE)
    seed(store, "sync", 1000, parent=digest(session))
    challenge = client.post(
        "/api/v1/auth/sync-challenge",
        json={"version": 1, "uuid": UUID, "name": NAME, "receipt_token": issued["receipt_token"]},
    ).json()
    result = client.post(
        "/api/v1/auth/sync-verify",
        json={"challenge_id": challenge["challenge_id"], "receipt_token": issued["receipt_token"]},
    )
    assert result.status_code == 200
    assert store.sync_identity(result.json()["sync_token"])["uuid"] == UUID
    assert store.sync_identity("sync-0")["uuid"] == UUID


def test_full_pending_receipts_do_not_leave_an_orphan_link(setup):
    client, store, _ = setup
    seed(store, "receipt", 1000)
    result = verify(client)
    assert result.status_code == 503
    assert count(store, "link") == 0
    assert count(store, "challenge") == 0  # Ownership attempts remain single-use on failure.
    assert store.db.execute("SELECT COUNT(*) FROM link_codes").fetchone()[0] == 0


def test_code_collision_failure_rolls_back_link_and_receipt(setup, monkeypatch):
    client, store, _ = setup
    monkeypatch.setattr(auth_module.secrets, "choice", lambda _: "A")
    assert verify(client).status_code == 200
    assert verify(client).status_code == 503
    assert count(store, "link") == count(store, "receipt") == 1


@pytest.mark.parametrize("use_code", [False, True])
def test_session_capacity_failure_preserves_link_for_retry(setup, monkeypatch, use_code):
    client, store, _ = setup
    monkeypatch.setattr(auth_module, "CREDENTIAL_LIMIT", 2)
    seed(store, "session", 2)
    issued = verify(client).json()
    token = issued["user_code"] if use_code else issued["link_token"]
    result = complete(client, token)
    assert result.status_code == 503
    assert "set-cookie" not in result.headers
    assert store.get_link(token) is not None
    assert store.receipt_status(issued["receipt_token"])["status"] == "pending"
    store.revoke("session-0")
    assert complete(client, token).status_code == 200
    assert complete(client, token).status_code == 410


def test_confirmation_failure_restores_old_session_and_all_children(setup):
    client, store, _ = setup
    old = verify(client).json()
    assert complete(client, old["link_token"]).status_code == 200
    cookie = client.cookies.get(COOKIE)
    sync = store.issue("sync", UUID, NAME, 900, digest(cookie))
    party = store.issue("party", UUID, NAME, DAY, digest(cookie))
    issued = verify(client).json()
    with store.db:
        store.db.execute("""CREATE TRIGGER fail_confirmation BEFORE UPDATE OF remembered ON auth
            WHEN NEW.kind='receipt' AND NEW.remembered=1
            BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
        complete(client, issued["link_token"])
    assert client.cookies.get(COOKIE) == cookie
    assert count(store, "session") == 1
    assert store.get_link(issued["link_token"]) is not None
    assert store.receipt_status(old["receipt_token"])["status"] == "linked"
    assert store.sync_identity(sync) is not None
    assert store.party_identity(party) is not None
    with store.db:
        store.db.execute("DROP TRIGGER fail_confirmation")
    assert complete(client, issued["link_token"]).status_code == 200
    assert store.get(cookie, "session") is None
    assert store.get(sync, "sync") is None
    assert store.get(party, "party") is None


def test_resume_capacity_failure_preserves_link_and_old_expiry(setup, monkeypatch):
    client, store, now = setup
    first = verify(client).json()
    assert complete(client, first["link_token"]).status_code == 200
    cookie = client.cookies.get(COOKIE)
    expires = store.get(cookie, "session")["expires"]
    monkeypatch.setattr(auth_module, "CREDENTIAL_LIMIT", 1)
    now[0] += 61
    issued = verify(client).json()
    result = client.post("/api/v1/auth/resume", headers=ORIGIN, json={"token": issued["user_code"]})
    assert result.status_code == 503
    assert "set-cookie" not in result.headers
    assert store.get(cookie, "session")["expires"] == expires
    assert store.get_link(issued["link_token"]) is not None
    assert store.receipt_status(first["receipt_token"])["status"] == "linked"


def test_atomic_browser_completion_under_concurrent_code_and_link_redemption(setup):
    client, store, _ = setup
    issued = verify(client).json()

    def finish(token):
        try:
            return store.finish_link(token, "", remember=True)
        except HTTPException as failure:
            assert failure.status_code == 410
            return None

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(finish, [issued["link_token"], issued["user_code"]] * 4))
    assert sum(result is not None for result in results) == 1
    assert count(store, "session") == 1
    assert store.receipt_status(issued["receipt_token"])["status"] == "linked"


def test_concurrent_link_issuance_cannot_exceed_pending_budget(setup, monkeypatch):
    _, store, _ = setup
    monkeypatch.setattr(auth_module, "PENDING_LIMIT", 1)

    def issue(_):
        try:
            return store.issue_link(UUID, NAME)
        except HTTPException as failure:
            assert failure.status_code == 503
            return None

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(issue, range(8)))
    assert sum(result is not None for result in results) == 1
    assert count(store, "link") == count(store, "receipt") == 1
    assert store.db.execute("SELECT COUNT(*) FROM link_codes").fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["sync", "party", "session", "receipt"])
def test_established_credential_limit_boundaries_and_expiry(setup, monkeypatch, kind):
    _, store, now = setup
    monkeypatch.setattr(auth_module, "CREDENTIAL_LIMIT", 3)
    # Unique parents avoid party replacement; this test isolates the admission bound.
    for i in range(3):
        store.issue(kind, UUID, NAME, 60, str(i), remembered=kind == "receipt")
        assert count(store, kind) == i + 1
    with pytest.raises(HTTPException) as failure:
        store.issue(kind, UUID, NAME, 60, "new", remembered=kind == "receipt")
    assert failure.value.status_code == 503
    assert count(store, kind) == 3
    now[0] += 60
    store.issue(kind, UUID, NAME, 60, "new", remembered=kind == "receipt")
    assert count(store, kind) == 1


def test_replacing_browser_session_at_capacity_is_allowed(setup, monkeypatch):
    client, store, _ = setup
    monkeypatch.setattr(auth_module, "CREDENTIAL_LIMIT", 1)
    first = verify(client).json()
    assert complete(client, first["link_token"]).status_code == 200
    second = verify(client).json()
    assert complete(client, second["link_token"]).status_code == 200
    assert count(store, "session") == count(store, "receipt") == 1


def test_cleanup_removes_legacy_orphans_without_removing_valid_credentials(setup):
    _, store, now = setup
    session = store.issue("session", UUID, NAME, 60)
    for kind in ("sync", "party", "receipt"):
        for parent in (digest(session), "missing-parent"):
            store.issue(kind, UUID, NAME, DAY, parent, remembered=kind == "receipt")
    pending = store.issue("receipt", UUID, NAME, 300, "pending-link")
    store.cleanup()
    assert count(store, "receipt") == 2
    assert count(store, "sync") == count(store, "party") == 1
    now[0] += 60
    store.cleanup()
    assert count(store, "sync") == count(store, "party") == count(store, "session") == 0
    assert store.receipt_status(pending)["status"] == "pending"


def test_startup_cleanup_preserves_existing_valid_sessions(tmp_path):
    path = tmp_path / "auth.sqlite3"
    store = AuthStore(path, clock=lambda: 100)
    session = store.issue("session", UUID, NAME, DAY)
    receipt = store.issue("receipt", UUID, NAME, DAY, digest(session), remembered=True)
    orphan = store.issue("sync", UUID, NAME, DAY, "missing-parent")
    store.close()
    store = AuthStore(path, clock=lambda: 101)
    try:
        assert store.get(session, "session") is not None
        assert store.receipt_status(receipt)["status"] == "linked"
        assert store.get(orphan, "sync") is None
    finally:
        store.close()
