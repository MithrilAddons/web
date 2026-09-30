import json
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.moderation import Moderation
from mithril_web.moderation_api import Sanction
from mithril_web.player_card import PlayerCardCache
from mithril_web.privacy import Privacy
from mithril_web.record_store import RecordStore
from mithril_web.skins import SkinCache
from test_moderation import MOD, OWNER, USER, post, seed
from test_moderation import setup as setup


def erase(client, headers, scope="account"):
    return client.post(
        "/api/v1/auth/erase",
        headers=headers,
        json={"version": 1, "scope": scope, "confirmation": "DELETE"},
    )


def test_record_erasure_preserves_link_but_revokes_sync_and_cached_bests(setup):
    client, app, _, headers, tokens = setup
    seed(app)
    result = erase(client, headers[USER], "records")
    assert result.status_code == 200, result.text
    assert app.state.records.read(USER) == []
    assert app.state.auth.sync_identity(tokens[USER]["sync"]) is None
    assert app.state.auth.party_identity(tokens[USER]["party"])["uuid"] == USER
    assert client.get("/api/v1/auth/session", headers=headers[USER]).json()["authenticated"]


def test_account_erasure_is_available_while_banned_and_does_not_remove_ban(setup):
    client, app, _, headers, tokens = setup
    seed(app)
    post(client, headers[MOD], "sanction", uuid=USER, kind="ban")
    assert erase(client, headers[USER]).status_code == 200
    assert app.state.records.read(USER) == []
    assert app.state.auth.party_identity(tokens[USER]["party"]) is None
    assert not client.get("/api/v1/auth/session", headers=headers[USER]).json()["authenticated"]
    with pytest.raises(HTTPException):
        app.state.moderation.check(USER)
    assert app.state.moderation.audit(OWNER, 100)["entries"][0]["action"] == "sanction"


def test_erasure_requires_session_origin_and_explicit_confirmation(setup):
    client, app, _, headers, _ = setup
    seed(app)
    assert erase(client, {}).status_code == 403
    assert erase(client, {"Origin": "https://mithril.foo"}).status_code == 401
    assert erase(client, {**headers[USER], "Origin": "https://evil.invalid"}).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/erase",
            headers=headers[USER],
            json={"version": 1, "scope": "account", "confirmation": "yes"},
        ).status_code
        == 422
    )
    assert app.state.records.read(USER)


def test_restore_replays_erasure_without_deleting_later_legitimate_records(setup, tmp_path):
    client, app, _, headers, _ = setup
    seed(app)
    backup = tmp_path / "backup.db"
    with closing(sqlite3.connect(backup)) as copy:
        app.state.records.db.backup(copy)
    assert erase(client, headers[USER], "records").status_code == 200
    # Normal restart/replay honors the applied marker and preserves later new runs.
    seed(app)
    app.state.privacy.replay()
    assert app.state.records.read(USER)
    restored_path = tmp_path / "restored.db"
    shutil.copyfile(backup, restored_path)
    restored = RecordStore(restored_path)
    try:
        moderation = Moderation(restored, OWNER)
        Privacy(app.state.auth, moderation, tmp_path / "auth.db")
        assert restored.read(USER) == []
    finally:
        restored.close()


def test_inflight_ownership_proof_cannot_recreate_deleted_link(tmp_path):
    started, finish = Event(), Event()

    def profile(name, _):
        started.set()
        assert finish.wait(3)
        return {"id": USER, "name": name}

    app = create_app(database=tmp_path / "auth.db", profile_lookup=profile)
    with TestClient(app, base_url="https://mithril.foo") as client:
        token = app.state.auth.issue("session", USER, "Synthetic", DAY)
        headers = {"Origin": "https://mithril.foo", "Cookie": f"{COOKIE}={token}"}
        challenge = client.post(
            "/api/v1/auth/challenge", json={"version": 1, "uuid": USER, "name": "Synthetic"}
        ).json()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                client.post, "/api/v1/auth/verify", json={"challenge_id": challenge["challenge_id"]}
            )
            assert started.wait(3)
            assert erase(client, headers).status_code == 200
            finish.set()
            assert pending.result(3).status_code == 401
        assert (
            app.state.auth.db.execute("SELECT COUNT(*) FROM auth WHERE uuid=?", (USER,)).fetchone()[
                0
            ]
            == 0
        )


def test_ledger_expiry_and_damage_refusal(setup):
    client, app, now, headers, _ = setup
    assert erase(client, headers[USER], "records").status_code == 200
    ledger = app.state.privacy.ledger
    assert json.loads(ledger.read_text())["uuid"] == USER
    now[0] += 7 * DAY
    app.state.privacy.cleanup()
    assert ledger.read_text() == ""
    ledger.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        app.state.privacy.replay()


def test_erasure_preserves_only_case_held_solo_evidence(setup):
    client, app, now, headers, _ = setup
    store = app.state.records
    from mithril_web.solo_evidence import SoloStart

    attempt = store.start(USER, SoloStart(version=2, floor="F7", elapsed_ms=0, ticks=0, paul=False))
    record = seed(app, evidence=attempt["attempt_id"])
    app.state.moderation.sanction(
        MOD,
        Sanction(
            version=1,
            reason="Review",
            uuid=USER,
            kind="ban",
            expires=int(now[0] + DAY),
            record_ids=[record],
        ),
    )
    assert erase(client, headers[USER]).status_code == 200
    assert store.read(USER) == []
    assert store.db.execute(
        "SELECT 1 FROM solo_attempts WHERE id=?", (attempt["attempt_id"],)
    ).fetchone()
    now[0] += DAY
    store.cleanup()
    assert not store.db.execute("SELECT 1 FROM solo_attempts").fetchone()


@pytest.mark.parametrize("cache_type", [SkinCache, PlayerCardCache])
def test_erasure_cancels_pending_cache_publication(cache_type):
    started, finish = Event(), Event()

    def loader(_):
        started.set()
        assert finish.wait(3)
        return {"synthetic": True}

    cache = cache_type(loader=loader)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(cache.get, USER)
        assert started.wait(3)
        cache.erase(USER)
        finish.set()
        assert pending.result(3) is None
    assert USER not in cache.entries
    assert not cache.erased_pending


def test_restore_command_rejects_expired_backups_and_missing_ledger(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "restore_tool", Path(__file__).parents[2] / "tools/replay_erasures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = datetime.now(UTC)
    auth_path = tmp_path / "auth.db"
    expired = now - timedelta(days=7)
    recent = now - timedelta(hours=1)
    with pytest.raises(ValueError, match="seven days"):
        module.replay(auth_path, expired, now)
    with pytest.raises(ValueError, match="preserve"):
        module.replay(auth_path, recent, now)
