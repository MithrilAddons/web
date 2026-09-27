"""Synthetic sessions and a fake clock only; never connects to Minecraft or Hypixel."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY, digest
from mithril_web.parties import CLASSES, PartyError

UUID = "a" * 32


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    profile = {"id": UUID, "name": "Alpha"}
    app = create_app(
        database=tmp_path / "auth.db", clock=lambda: now[0], profile_lookup=lambda *_: profile
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        store = app.state.auth
        session = store.issue("session", UUID, "Alpha", 60 * DAY)
        receipt = store.issue("receipt", UUID, "Alpha", 60 * DAY, digest(session), True)
        yield client, app, now, profile, session, receipt


def authorize(client, receipt):
    proof = client.post(
        "/api/v1/auth/party-challenge",
        json={"version": 1, "uuid": UUID, "name": "Alpha", "receipt_token": receipt},
    )
    assert proof.status_code == 200
    response = client.post(
        "/api/v1/auth/party-verify",
        json={"challenge_id": proof.json()["challenge_id"], "receipt_token": receipt},
    )
    assert response.status_code == 200
    assert response.json()["expires_in_seconds"] == 30 * DAY
    return {"Authorization": "Bearer " + response.json()["party_token"]}


def full_party(app):
    finder = app.state.finder
    ids = [letter * 32 for letter in "abcde"]
    names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"]
    for uuid, name in zip(ids, names, strict=True):
        finder.seen(uuid, name, "web")
        finder.set_stats(uuid, {})
    party_id = finder.publish(UUID, "M7", "archer", list(CLASSES), False, {}, {})
    for uuid, role in zip(ids[1:], CLASSES[1:], strict=True):
        finder.reserve(uuid, party_id, role)
    for uuid, name in zip(ids, names, strict=True):
        finder.seen(uuid, name, "mod")
    return finder, finder.parties[party_id], ids, names


def test_shared_mod_handoff_contract(setup):
    client, app, _, _, _, receipt = setup
    headers = authorize(client, receipt)
    _, _, _, _ = full_party(app)
    response = client.post(
        "/api/v1/party/mod/presence", headers=headers, json={"version": 1, "online": True}
    )
    assert response.status_code == 200
    actual = response.json()
    assert actual.pop("activity") == {"floor": "M7", "leader": "Alpha", "members": 5}
    assert actual.pop("chat_party_id") == actual["party"]["party_id"]
    actual["party"]["party_id"] = "party0000001"
    actual["party"]["handoff_id"] = "batch0000001"
    fixture = Path(__file__).resolve().parents[2] / "contracts/mod-party-v1.json"
    assert actual == json.loads(fixture.read_text())


def test_party_scope_cannot_upload_or_log_in_and_logout_revokes(setup):
    client, app, _, _, session, receipt = setup
    headers = authorize(client, receipt)
    token = headers["Authorization"][7:]
    assert app.state.auth.sync_identity(token) is None
    client.cookies.set(COOKIE, token)
    assert not client.get("/api/v1/auth/session").json()["authenticated"]
    assert (
        client.post(
            "/api/v1/auth/sync-records",
            headers=headers,
            json={
                "version": 1,
                "records": [{"floor": "F7", "kind": "terminals", "real_ms": 40000, "ticks": 780}],
            },
        ).status_code
        == 401
    )
    assert (
        client.post("/api/v1/party/mod/presence", headers=headers, json={"version": 1}).status_code
        == 200
    )
    app.state.auth.revoke(session)
    assert (
        client.post("/api/v1/party/mod/presence", headers=headers, json={"version": 1}).status_code
        == 401
    )


def test_presence_activity_tracks_own_search_party_and_departure(setup):
    client, app, _, _, _, receipt = setup
    headers = authorize(client, receipt)
    finder = app.state.finder

    def activity():
        response = client.post(
            "/api/v1/party/mod/presence",
            headers=headers,
            json={"version": 1, "online": False},
        )
        assert response.status_code == 200
        return response.json()["activity"]

    assert activity() is None
    finder.seen(UUID, "Alpha", "web")
    finder.set_stats(UUID, {})
    finder.look(UUID, "F7", ["archer"], None)
    assert activity() == {"floor": "F7", "leader": None, "members": 0}
    finder.stop_looking(UUID)
    assert activity() is None
    finder, party, ids, _ = full_party(app)
    assert activity() == {"floor": "M7", "leader": "Alpha", "members": 5}
    finder.leave(ids[-1])
    assert activity()["members"] == 4
    finder.leave(UUID)
    assert activity() is None


def test_expiry_renewal_and_scoped_proof_replay(setup):
    client, app, now, profile, _, receipt = setup
    headers = authorize(client, receipt)
    now[0] += 30 * DAY - 1
    assert app.state.auth.party_identity(headers["Authorization"][7:])
    now[0] += 1
    assert app.state.auth.party_identity(headers["Authorization"][7:]) is None
    renewed = authorize(client, receipt)
    assert app.state.auth.party_identity(renewed["Authorization"][7:])
    proof = client.post(
        "/api/v1/auth/party-challenge",
        json={"version": 1, "uuid": UUID, "name": "Alpha", "receipt_token": receipt},
    ).json()
    body = {"challenge_id": proof["challenge_id"], "receipt_token": receipt}
    assert client.post("/api/v1/auth/sync-verify", json=body).status_code == 410
    profile["id"] = "f" * 32
    assert client.post("/api/v1/auth/party-verify", json=body).status_code == 401
    profile["id"] = UUID
    assert client.post("/api/v1/auth/party-verify", json=body).status_code == 410


def test_one_automatic_round_then_explicit_retry_only_and_roster_completion(setup):
    client, app, now, _, _, receipt = setup
    headers = authorize(client, receipt)
    finder, party, _, names = full_party(app)
    body = {
        "version": 1,
        "party_id": party.id,
        "handoff_id": party.handoff_id,
        "leader": "Alpha",
        "members": ["Alpha"],
        "retry": False,
    }
    url = "/api/v1/party/mod/invite"
    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 200
    assert first.json()["invite"] == names[1:]
    assert client.post(url, headers=headers, json=body).json()["invite"] == []
    assert client.post(url, headers=headers, json={**body, "retry": True}).status_code == 409
    now[0] += 10
    again = client.post(url, headers=headers, json={**body, "members": names[:3], "retry": True})
    assert again.json()["invite"] == names[3:]
    assert party.id in finder.parties
    del body["retry"]
    complete = client.post(
        "/api/v1/party/mod/roster", headers=headers, json={**body, "members": names}
    )
    assert complete.json()["party"] is None
    assert finder.parties[party.id].completed
    assert complete.json()["activity"] == {"floor": "M7", "leader": "Alpha", "members": 5}
    assert finder.players[UUID].notices[-1]["kind"] == "party_joined"


def test_offline_stale_roster_and_foreign_party_cannot_trigger_invites(setup):
    _, app, _, _, _, _ = setup
    finder, party, ids, names = full_party(app)
    args = (UUID, party.id, party.handoff_id)
    for leader, roster in (("Beta", names[:2]), ("Alpha", ["Alpha", "Outsider"])):
        with pytest.raises(PartyError, match="game_party_conflict"):
            finder.invite(*args, leader, roster, False)
    finder.seen(ids[-1], names[-1], "mod", online=False)
    with pytest.raises(PartyError, match="not_ready"):
        finder.invite(*args, "Alpha", ["Alpha"], False)
    finder.leave(ids[-1])
    with pytest.raises(PartyError, match="stale_handoff"):
        finder.invite(*args, "Alpha", ["Alpha"], False)
    assert party.invited_at is None


def test_after_inviting_disconnects_do_not_receive_the_offline_no_show_ban(setup):
    _, app, now, _, _, _ = setup
    finder, party, ids, names = full_party(app)
    finder.invite(UUID, party.id, party.handoff_id, "Alpha", ["Alpha"], False)
    now[0] += 301
    for uuid, name in zip(ids[:-1], names[:-1], strict=True):
        finder.seen(uuid, name, "mod")
    finder.sweep()
    assert finder.players[ids[-1]].banned_until == 0
    assert finder.players[ids[-1]].party is None
    assert party.id in finder.parties and party.full_since is None
