import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.moderation import Moderation
from mithril_web.moderation_api import CaseAction, RecordAction, Sanction
from mithril_web.parties import player_stats
from mithril_web.record_store import RecordStore
from test_party_api import SUMMARY

OWNER, MOD, USER, OTHER = (char * 32 for char in "abcd")
ORIGIN = "https://mithril.foo"


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        owner_uuid=OWNER,
        network_key=b"synthetic-test-key-never-use-live!",
        party_wait=0.01,
        card_loader=lambda _: SUMMARY,
    )
    with TestClient(app, base_url=ORIGIN) as client:
        headers, tokens = {}, {}
        for uuid in (OWNER, MOD, USER, OTHER):
            token = app.state.auth.issue("session", uuid, "Synthetic", 30 * DAY)
            headers[uuid] = {"Cookie": f"{COOKIE}={token}", "Origin": ORIGIN}
            parent = app.state.auth.get(token, "session")["token"]
            tokens[uuid] = {
                kind: app.state.auth.issue(kind, uuid, "Synthetic", 900, server_id=parent)
                for kind in ("sync", "party")
            }
        app.state.moderation.grant(OWNER, MOD, True, "Trusted maintainer")
        yield client, app, now, headers, tokens


def post(client, headers, path, **body):
    return client.post(
        f"/api/v1/moderation/{path}",
        headers=headers,
        json={"version": 1, "reason": "Synthetic review", **body},
    )


def seed(app, uuid=USER, evidence=None):
    store = app.state.records
    with store.lock, store.db:
        return store._record(uuid, "F7", "solo_clear", 100_000, 2000, "legacy", evidence)


def test_access_owner_grants_csrf_and_revocation(setup):
    client, app, _, headers, _ = setup
    assert client.get("/api/v1/moderation/access").status_code == 401
    assert client.get("/api/v1/moderation/access", headers=headers[USER]).status_code == 403
    assert client.get("/api/v1/moderation/access", headers=headers[OWNER]).json()["role"] == "owner"
    assert post(client, headers[MOD], "access", uuid=USER, enabled=True).status_code == 403
    foreign = {**headers[OWNER], "Origin": "https://example.invalid"}
    assert post(client, foreign, "access", uuid=USER, enabled=True).status_code == 403
    assert post(client, headers[OWNER], "access", uuid=MOD, enabled=False).status_code == 200
    assert client.get("/api/v1/moderation/audit", headers=headers[MOD]).status_code == 403
    assert app.state.moderation.role(MOD) is None
    assert app.state.moderation.audit(OWNER, 100)["entries"][0]["actor"] == OWNER


def test_record_correction_audit_and_cache_clear_without_hypixel(setup):
    client, app, _, headers, _ = setup
    record = seed(app)
    finder = app.state.finder
    finder.seen(USER, "Synthetic", "web")
    finder.set_stats(USER, player_stats(SUMMARY, app.state.records.read(USER)))
    response = post(
        client,
        headers[MOD],
        "record",
        record_id=record,
        expected_status="eligible",
        action="correct",
        real_ms=150_000,
        ticks=3000,
    )
    assert response.status_code == 200, response.text
    assert app.state.records.read(USER)[0]["real_ms"] == 150_000
    assert finder.players[USER].stats["solo_ms"]["F7"] == 150_000
    rows = app.state.moderation.inspect(MOD, USER)["records"]
    manual = next(r for r in rows if r["source"] == "manual")
    assert (
        post(
            client,
            headers[MOD],
            "record",
            record_id=manual["id"],
            expected_status="eligible",
            action="invalidate",
        ).status_code
        == 200
    )
    assert app.state.records.read(USER) == []
    assert finder.players[USER].stats["solo_ms"]["F7"] is None
    audit = app.state.moderation.audit(OWNER, 100)["entries"]
    change = next(r for r in audit if r["action"] == "record_correct")
    assert change["actor"] == MOD
    assert json.loads(change["before_json"])["real_ms"] == 100_000
    assert json.loads(change["after_json"])["replacement"]["real_ms"] == 150_000
    assert (
        post(
            client,
            headers[MOD],
            "record",
            record_id=record,
            expected_status="eligible",
            action="invalidate",
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            headers[MOD],
            "record",
            record_id=record,
            expected_status="invalidated",
            action="restore",
        ).status_code
        == 200
    )


def test_failed_audit_rolls_back_record_change(setup):
    _, app, _, _, _ = setup
    record = seed(app)
    action = RecordAction(
        version=1,
        reason="Review",
        record_id=record,
        expected_status="eligible",
        action="invalidate",
    )
    with patch.object(app.state.moderation, "_audit", side_effect=RuntimeError("Disk failure")):
        with pytest.raises(RuntimeError):
            app.state.moderation.record_action(MOD, action)
    assert app.state.records.read(USER)[0]["real_ms"] == 100_000


def test_ban_ejects_and_blocks_web_mod_and_records_but_not_account_access(setup):
    client, app, now, headers, tokens = setup
    finder = app.state.finder
    finder.seen(USER, "Synthetic", "web")
    finder.set_stats(USER, player_stats(SUMMARY, []))
    finder.look(USER, "F7", ["mage"], None)
    response = post(client, headers[MOD], "sanction", uuid=USER, kind="ban", expires=1010)
    assert response.status_code == 200, response.text
    assert USER not in finder.players and USER not in finder.lookers["F7"]
    assert client.get("/api/v1/party/listings?floor=F7", headers=headers[USER]).status_code == 403
    assert client.get("/api/v1/auth/session", headers=headers[USER]).status_code == 200
    mod_headers = {"Authorization": f"Bearer {tokens[USER]['party']}"}
    assert (
        client.post(
            "/api/v1/party/mod/presence", headers=mod_headers, json={"version": 1}
        ).status_code
        == 403
    )
    record_headers = {"Authorization": f"Bearer {tokens[USER]['sync']}"}
    body = dict(version=2, floor="F7", elapsed_ms=0, ticks=0, paul=False)
    assert (
        client.post("/api/v1/records/solo-start", headers=record_headers, json=body).status_code
        == 403
    )
    now[0] = 1010
    assert (
        client.post("/api/v1/records/solo-start", headers=record_headers, json=body).status_code
        == 200
    )


def test_mute_blocks_both_chat_routes_only(setup):
    client, _, _, headers, tokens = setup
    assert post(client, headers[MOD], "sanction", uuid=USER, kind="mute").status_code == 200
    body = dict(
        version=1, party_id="a" * 12, request_id="00000000-0000-4000-8000-000000000000", text="hi"
    )
    assert client.post("/api/v1/party/chat", headers=headers[USER], json=body).status_code == 403
    mod_headers = {"Authorization": f"Bearer {tokens[USER]['party']}"}
    assert (
        client.post("/api/v1/party/mod/chat/send", headers=mod_headers, json=body).status_code
        == 403
    )
    assert (
        client.post("/api/v1/party/state", headers=headers[USER], json={"version": 1}).status_code
        == 200
    )


def test_network_privacy_expiry_and_spoofed_forwarded_header(setup):
    client, app, now, headers, _ = setup
    moderation = app.state.moderation
    moderation.check(USER, "192.0.2.1", remember=True)
    moderation.check(OTHER, "::ffff:192.0.2.1", remember=True)
    response = post(client, headers[MOD], "sanction", uuid=USER, kind="network_ban", expires=2000)
    case = response.json()["case"]
    assert "network" not in case and "192.0.2.1" not in response.text
    assert moderation.affected_accounts(case) == {USER, OTHER}
    with pytest.raises(HTTPException, match="banned"):
        moderation.check(OTHER, "192.0.2.1")
    moderation.check(OTHER, "192.0.2.2")
    # Caller headers are never parsed as trusted connection addresses by application code.
    assert (
        client.get(
            "/api/v1/party/listings?floor=F7",
            headers={**headers[OTHER], "X-Forwarded-For": "192.0.2.1"},
        ).status_code
        == 200
    )
    history = client.get("/api/v1/moderation/audit", headers=headers[MOD]).text
    assert moderation._fingerprint("192.0.2.1") not in history
    now[0] = 2000
    moderation.check(OTHER, "192.0.2.1")
    moderation.cleanup()
    assert (
        moderation.db.execute("SELECT network FROM sanctions WHERE id=?", (case["id"],)).fetchone()[
            0
        ]
        is None
    )
    now[0] += DAY
    moderation.cleanup()
    assert moderation.db.execute("SELECT COUNT(*) FROM account_networks").fetchone()[0] == 0


def test_permanent_ban_appeal_holds_and_close_expiry(setup):
    _, app, now, _, _ = setup
    record = seed(app, evidence="e" * 43)
    moderation = app.state.moderation
    body = Sanction(version=1, reason="Review", uuid=USER, kind="ban", record_ids=[record])
    case = moderation.sanction(MOD, body)
    assert case["expires"] is None and case["evidence_until"] == now[0] + 30 * DAY

    def action(value):
        return CaseAction(version=1, reason="Appeal review", case_id=case["id"], action=value)

    moderation.case_action(MOD, action("open_appeal"))
    assert moderation.db.execute("SELECT until FROM evidence_holds").fetchone()[0] is None
    now[0] += 31 * DAY
    moderation.case_action(MOD, action("close_appeal"))
    assert moderation.db.execute("SELECT until FROM evidence_holds").fetchone()[0] < now[0]
    with pytest.raises(HTTPException):
        moderation.check(USER)
    moderation.case_action(MOD, action("revoke"))
    moderation.check(USER)


def test_permission_and_sanction_survive_restart(tmp_path):
    path = tmp_path / "records.db"
    records = RecordStore(path)
    mod = Moderation(records, OWNER)
    mod.grant(OWNER, MOD, True, "Maintainer")
    mod.sanction(MOD, Sanction(version=1, reason="Abuse", uuid=USER, kind="ban"))
    records.close()
    records = RecordStore(path)
    try:
        mod = Moderation(records, OWNER)
        assert mod.role(MOD) == "moderator"
        with pytest.raises(HTTPException):
            mod.check(USER)
        assert mod.audit(OWNER, 100)["entries"][0]["actor"] == MOD
    finally:
        records.close()


def test_missing_owner_fails_closed_and_invalid_requests_do_not_change_data(setup):
    client, app, _, headers, _ = setup
    assert post(client, headers[OWNER], "sanction", uuid=OWNER, kind="ban").status_code == 409
    assert post(client, headers[MOD], "sanction", uuid=USER, kind="network_ban").status_code == 409
    assert (
        post(client, headers[MOD], "sanction", uuid=USER, kind="ban", reason="  ").status_code
        == 422
    )
    assert (
        post(client, headers[MOD], "sanction", uuid=USER, kind="ban", expires=900).status_code
        == 422
    )
    before = len(app.state.moderation.audit(OWNER, 100)["entries"])
    assert (
        post(
            client, headers[MOD], "sanction", uuid=USER, kind="ban", record_ids=["z" * 43]
        ).status_code
        == 422
    )
    assert app.state.moderation.inspect(MOD, USER)["cases"] == []
    assert len(app.state.moderation.audit(OWNER, 100)["entries"]) == before


def test_old_current_best_is_visible_beyond_recent_history_limit(setup):
    _, app, now, _, _ = setup
    oldest = seed(app)
    with app.state.records.lock, app.state.records.db:
        for index in range(205):
            now[0] += 1
            app.state.records._record(
                USER, "F7", "solo_clear", 200_000 + index, 4000 + index, "live", None
            )
    rows = app.state.moderation.inspect(MOD, USER)["records"]
    assert oldest in {row["id"] for row in rows}
    assert len(rows) == 201
