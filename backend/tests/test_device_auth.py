"""Native finder sessions use synthetic ownership proofs and isolated databases."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY, digest
from mithril_web.moderation_api import Sanction

UUID = "a" * 32
OTHER = "b" * 32
NAME = "SyntheticOne"
ORIGIN = {"Origin": "https://mithril.foo"}
PUBLISH = {
    "version": 1,
    "floor": "M7",
    "leader_class": "mage",
    "roles": ["archer", "berserk", "healer", "mage", "tank"],
    "allow_duplicates": False,
    "rules": {"shared": {}, "per_class": {}, "exempt": []},
}


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    app = create_app(
        database=tmp_path / "auth.sqlite3",
        owner_uuid="c" * 32,
        clock=lambda: now[0],
        party_wait=0.1,
        profile_lookup=lambda *_: {"id": UUID, "name": NAME},
        card_loader=lambda _: {
            "catacombs": {"level": 50.0},
            "magical_power": 1400,
            "class_levels": dict.fromkeys(PUBLISH["roles"], 50.0),
            "floors": [{"floor": "M7", "s_plus_ms": 300000}],
        },
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        yield client, app, now


def challenge(client):
    response = client.post(
        "/api/v1/auth/device-challenge",
        json={
            "version": 1,
            "uuid": UUID,
            "name": NAME,
            "client_nonce": "c" * 64,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def login(client):
    response = client.post(
        "/api/v1/auth/device-verify",
        json={
            "challenge_id": challenge(client)["challenge_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_native_login_is_nonce_bound_single_use_and_sets_no_cookie(setup):
    client, app, _ = setup
    proof = challenge(client)
    value = f"mithrilpf:ownership:v2:device:{UUID}:{'c' * 64}:{proof['server_nonce']}"
    assert proof["server_id"] == hashlib.sha256(value.encode()).hexdigest()[:39]
    response = client.post(
        "/api/v1/auth/device-verify", json={"challenge_id": proof["challenge_id"]}
    )
    assert response.status_code == 200
    assert not response.cookies
    credentials = response.json()
    assert credentials["user"] == {"uuid": UUID, "name": NAME}
    assert app.state.auth.receipt_status(credentials["receipt_token"])["status"] == "linked"
    assert (
        client.post(
            "/api/v1/auth/device-verify", json={"challenge_id": proof["challenge_id"]}
        ).status_code
        == 410
    )
    assert (
        client.post(
            "/api/v1/auth/device-challenge", json={"version": 1, "uuid": UUID, "name": NAME}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/auth/verify", json={"challenge_id": challenge(client)["challenge_id"]}
        ).status_code
        == 410
    )


def test_credentials_cannot_cross_browser_native_or_scoped_boundaries(setup):
    client, app, _ = setup
    device = login(client)["device_token"]
    browser = app.state.auth.issue("session", UUID, NAME, DAY)
    party = app.state.auth.issue("party", UUID, NAME, DAY, server_id=digest(device))
    for token in (browser, party):
        assert (
            client.post(
                "/api/v1/party/client/state", headers=headers(token), json={"version": 1}
            ).status_code
            == 401
        )
    assert client.get("/api/v1/auth/session", headers={"Cookie": f"{COOKIE}={device}"}).json() == {
        "authenticated": False
    }
    assert (
        client.post(
            "/api/v1/party/client/state", headers={**headers(device), **ORIGIN}, json={"version": 1}
        ).status_code
        == 403
    )
    assert client.get("/api/v1/party/client/listings?floor=M7").status_code == 401
    assert (
        client.post(
            "/api/v1/party/state", headers={**headers(device), **ORIGIN}, json={"version": 1}
        ).status_code
        == 401
    )


def test_native_parent_survives_browser_logout_and_cleanup_then_revokes_children(setup):
    client, app, _ = setup
    credentials = login(client)
    device, receipt = credentials["device_token"], credentials["receipt_token"]
    for scope in ("party", "sync"):
        proof = client.post(
            f"/api/v1/auth/{scope}-challenge",
            json={
                "version": 1,
                "uuid": UUID,
                "name": NAME,
                "client_nonce": "d" * 64,
                "receipt_token": receipt,
            },
        ).json()
        response = client.post(
            f"/api/v1/auth/{scope}-verify",
            json={
                "challenge_id": proof["challenge_id"],
                "receipt_token": receipt,
            },
        )
        assert response.status_code == 200
        credentials[scope] = response.json()[f"{scope}_token"]
    browser = app.state.auth.issue("session", UUID, NAME, DAY)
    app.state.auth.revoke(browser)
    app.state.auth.cleanup()
    assert app.state.auth.party_identity(credentials["party"])["uuid"] == UUID
    assert app.state.auth.sync_identity(credentials["sync"])["uuid"] == UUID
    assert client.post("/api/v1/auth/device-logout", headers=headers(device)).status_code == 200
    assert app.state.auth.party_identity(credentials["party"]) is None
    assert app.state.auth.sync_identity(credentials["sync"]) is None
    assert app.state.auth.receipt_status(receipt)["status"] == "expired"
    assert client.get("/api/v1/auth/device-session", headers=headers(device)).status_code == 401


def test_device_management_is_account_bound_and_requires_origin(setup):
    client, app, _ = setup
    device = login(client)["device_token"]
    session = app.state.auth.issue("session", UUID, NAME, DAY)
    other = app.state.auth.issue("session", OTHER, "SyntheticTwo", DAY)
    own = {"Cookie": f"{COOKIE}={session}"}
    foreign = {"Cookie": f"{COOKIE}={other}", **ORIGIN}
    assert client.get("/api/v1/auth/devices", headers=foreign).json()["devices"] == []
    listed = client.get("/api/v1/auth/devices", headers=own).json()["devices"]
    assert len(listed) == 1 and listed[0]["id"] == digest(device)
    assert device not in str(listed)
    payload = {"id": digest(device)}
    assert client.post("/api/v1/auth/devices/revoke", headers=own, json=payload).status_code == 403
    assert (
        client.post("/api/v1/auth/devices/revoke", headers=foreign, json=payload).status_code == 404
    )
    assert (
        client.post(
            "/api/v1/auth/devices/revoke", headers={**own, **ORIGIN}, json=payload
        ).status_code
        == 200
    )
    assert app.state.auth.get(device, "device") is None


def test_device_expiry_and_account_erasure_revoke_access(setup):
    client, app, now = setup
    credentials = login(client)
    token = credentials["device_token"]
    now[0] += 30 * DAY
    assert client.get("/api/v1/auth/device-session", headers=headers(token)).status_code == 401
    token = login(client)["device_token"]
    result = client.post(
        "/api/v1/auth/device-erase",
        headers=headers(token),
        json={
            "version": 1,
            "scope": "account",
            "confirmation": "DELETE",
        },
    )
    assert result.status_code == 200, result.text
    assert app.state.auth.get(token, "device") is None
    assert (
        client.get("/api/v1/party/client/listings?floor=M7", headers=headers(token)).status_code
        == 401
    )


def test_device_issue_is_atomic_when_receipt_capacity_fails(setup, monkeypatch):
    client, app, _ = setup
    monkeypatch.setattr("mithril_web.auth.CREDENTIAL_LIMIT", 1)
    app.state.auth.issue("receipt", OTHER, "SyntheticTwo", DAY, remembered=True)
    response = client.post(
        "/api/v1/auth/device-verify", json={"challenge_id": challenge(client)["challenge_id"]}
    )
    assert response.status_code == 503
    assert (
        app.state.auth.db.execute("SELECT COUNT(*) FROM auth WHERE kind='device'").fetchone()[0]
        == 0
    )


def test_device_cap_preserves_existing_sessions(setup):
    _, app, _ = setup
    for _ in range(10):
        app.state.auth.issue_device(UUID, NAME, "")
    with pytest.raises(HTTPException) as error:
        app.state.auth.issue_device(UUID, NAME, "")
    assert error.value.status_code == 409
    assert (
        app.state.auth.db.execute("SELECT COUNT(*) FROM auth WHERE kind='device'").fetchone()[0]
        == 10
    )


def test_device_logout_cannot_revoke_browser_children(setup):
    client, app, _ = setup
    token = app.state.auth.issue("session", UUID, NAME, DAY)
    child = app.state.auth.issue("party", UUID, NAME, DAY, server_id=digest(token))
    assert client.post("/api/v1/auth/device-logout", headers=headers(token)).status_code == 200
    assert app.state.auth.party_identity(child)["uuid"] == UUID


def test_mutes_and_bans_apply_to_native_finder_but_do_not_block_erasure(setup):
    client, app, _ = setup
    token = login(client)["device_token"]
    access = headers(token)
    party = client.post("/api/v1/party/client/publish", headers=access, json=PUBLISH).json()[
        "party"
    ]
    app.state.moderation.sanction(
        "c" * 32, Sanction(version=1, reason="Synthetic mute", uuid=UUID, kind="mute")
    )
    muted = client.post(
        "/api/v1/party/client/chat",
        headers=access,
        json={
            "version": 1,
            "party_id": party["id"],
            "request_id": "r" * 16,
            "text": "Blocked",
        },
    )
    assert muted.status_code == 403
    app.state.moderation.sanction(
        "c" * 32, Sanction(version=1, reason="Synthetic ban", uuid=UUID, kind="ban")
    )
    assert client.get("/api/v1/party/client/listings?floor=M7", headers=access).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/device-erase",
            headers=access,
            json={
                "version": 1,
                "scope": "account",
                "confirmation": "DELETE",
            },
        ).status_code
        == 200
    )


def test_native_publish_reserve_chat_edit_and_leave_reuse_finder_rules(setup):
    client, app, _ = setup
    leader = headers(login(client)["device_token"])
    joiner = headers(app.state.auth.issue_device(OTHER, "SyntheticTwo", "")[0])
    party = client.post("/api/v1/party/client/publish", headers=leader, json=PUBLISH)
    assert party.status_code == 200, party.text
    party_id = party.json()["party"]["id"]
    listing = client.get("/api/v1/party/client/listings?floor=M7", headers=joiner)
    assert listing.json()["parties"][0]["id"] == party_id
    assert (
        client.get(
            "/api/v1/party/client/listings?floor=M7",
            headers={**joiner, "If-None-Match": listing.headers["etag"]},
        ).status_code
        == 304
    )
    assert (
        client.post(
            "/api/v1/party/client/reserve",
            headers=joiner,
            json={"party_id": party_id, "role": "healer"},
        ).status_code
        == 200
    )
    sent = client.post(
        "/api/v1/party/client/chat",
        headers=joiner,
        json={"version": 1, "party_id": party_id, "request_id": "q" * 16, "text": "Ready"},
    )
    assert sent.status_code == 200, sent.text
    assert (
        client.post("/api/v1/party/client/pause", headers=joiner, json={"paused": True}).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/party/client/remove", headers=leader, json={"member": OTHER, "block": True}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/party/client/listings?floor=M7", headers=joiner).json()["parties"] == []
    )
    assert (
        client.get(f"/api/v1/party/client/listings/{party_id}", headers=joiner).status_code == 404
    )
    assert (
        client.post(
            "/api/v1/party/client/reserve",
            headers=joiner,
            json={"party_id": party_id, "role": "healer"},
        ).status_code
        == 404
    )
    assert client.post("/api/v1/party/client/leave", headers=leader, json={}).status_code == 200


def test_revocation_during_held_state_does_not_return_party_data(setup, monkeypatch):
    client, app, _ = setup
    token = login(client)["device_token"]
    first = client.post(
        "/api/v1/party/client/state", headers=headers(token), json={"version": 1}
    ).json()
    waiting, release = Event(), Event()

    async def hold(*_):
        from starlette.concurrency import run_in_threadpool

        waiting.set()
        await run_in_threadpool(release.wait, 5)

    monkeypatch.setattr("mithril_web.party_api.Waiters.wait", hold)
    with ThreadPoolExecutor() as pool:
        request = pool.submit(
            client.post,
            "/api/v1/party/client/state",
            headers=headers(token),
            json={"version": 1, "known": first["state_version"]},
        )
        try:
            assert waiting.wait(5)
            app.state.auth.revoke_device(token)
        finally:
            release.set()
        assert request.result(timeout=5).status_code == 401
