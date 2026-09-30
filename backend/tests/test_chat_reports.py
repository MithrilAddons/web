import json

from mithril_web.auth import DAY
from mithril_web.moderation_api import CaseAction, Sanction
from test_party_chat import IDS, body
from test_party_chat import chat as chat


def report(client, headers, party, message="1"):
    return client.post(
        "/api/v1/party/chat/report",
        headers=headers,
        json={"version": 1, "party_id": party, "message_id": message, "reason": "Abusive message"},
    )


def test_reports_capture_server_message_only_and_require_membership(chat):
    client, _, _, sessions, _, party, app = chat
    client.post("/api/v1/party/chat", headers=sessions[0], json=body(party, "Synthetic message"))
    assert report(client, sessions[2], party).status_code == 409
    assert report(client, sessions[1], party, "99").status_code == 404
    response = report(client, sessions[1], party)
    assert response.status_code == 200
    assert report(client, sessions[1], party).json() == response.json()
    app.state.moderation.owner = IDS[2]
    rows = app.state.moderation.chat.list(IDS[2])["reports"]
    assert len(rows) == 1
    assert json.loads(rows[0]["evidence"])["sender"]["uuid"] == IDS[0]
    assert json.loads(rows[0]["evidence"])["text"] == "Synthetic message"
    assert rows[0]["reporter"] == IDS[1]


def test_removal_hides_history_and_retry_and_keeps_mod_protocol_valid(chat):
    client, finder, _, sessions, mods, party, app = chat
    app.state.moderation.owner = IDS[2]
    client.post("/api/v1/party/chat", headers=sessions[0], json=body(party, "Synthetic message"))
    report_id = report(client, sessions[1], party).json()["report_id"]
    result = client.post(
        "/api/v1/moderation/chat",
        headers=sessions[2],
        json={
            "version": 1,
            "reason": "Confirmed violation",
            "report_id": report_id,
            "action": "hide",
        },
    )
    assert result.status_code == 200, result.text
    assert "Synthetic message" not in json.dumps(finder.personal(IDS[0]))
    assert (
        client.post(
            "/api/v1/party/chat", headers=sessions[0], json=body(party, "Synthetic message")
        ).status_code
        == 409
    )
    messages = client.post(
        "/api/v1/party/mod/chat/state",
        headers=mods[1],
        json={"version": 1, "party_id": party, "after": 0},
    ).json()
    assert messages["messages"] == [] and messages["latest"] == 1
    audit = app.state.moderation.audit(IDS[2], 100)["entries"]
    assert audit[0]["actor"] == IDS[2]
    assert "Synthetic message" not in json.dumps(audit)


def test_chat_retention_appeal_and_late_appeal_cannot_restore_detail(chat):
    client, _, now, sessions, _, party, app = chat
    mod = app.state.moderation
    mod.owner = IDS[2]
    client.post("/api/v1/party/chat", headers=sessions[0], json=body(party))
    report_id = report(client, sessions[1], party).json()["report_id"]
    case = mod.sanction(
        IDS[2], Sanction(version=1, reason="Abuse", uuid=IDS[0], kind="ban", report_ids=[report_id])
    )

    def appeal(action):
        return CaseAction(version=1, reason="Appeal review", case_id=case["id"], action=action)

    mod.case_action(IDS[2], appeal("open_appeal"))
    now[0] += 31 * DAY
    mod.cleanup()
    assert len(mod.chat.list(IDS[2])["reports"]) == 1
    mod.case_action(IDS[2], appeal("close_appeal"))
    mod.cleanup()
    assert mod.chat.list(IDS[2])["reports"] == []
    mod.case_action(IDS[2], appeal("open_appeal"))
    assert mod.chat.list(IDS[2])["reports"] == []


def test_audit_retention_keeps_active_and_appealed_cases(chat):
    _, _, now, _, _, _, app = chat
    mod = app.state.moderation
    mod.owner = IDS[2]
    case = mod.sanction(
        IDS[2],
        Sanction(version=1, reason="Abuse", uuid=IDS[0], kind="ban", expires=int(now[0] + DAY)),
    )
    now[0] += 180 * DAY
    mod.cleanup()
    assert len(mod.audit(IDS[2], 100)["entries"]) == 1
    mod.case_action(
        IDS[2], CaseAction(version=1, reason="Appeal", case_id=case["id"], action="open_appeal")
    )
    now[0] += 400 * DAY
    mod.cleanup()
    assert len(mod.inspect(IDS[2], IDS[0])["cases"]) == 1
    mod.case_action(
        IDS[2],
        CaseAction(version=1, reason="Appeal closed", case_id=case["id"], action="close_appeal"),
    )
    now[0] += 180 * DAY
    mod.cleanup()
    assert mod.inspect(IDS[2], IDS[0])["cases"] == []
    assert mod.audit(IDS[2], 100)["entries"] == []
