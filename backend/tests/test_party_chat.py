"""Real route calls with synthetic identities, isolated storage and no network."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, digest
from mithril_web.parties import CLASSES, Finder, PartyError, player_stats
from mithril_web.party_api import Waiters

ORIGIN = "https://mithril.foo"
IDS = [c * 32 for c in "abcdef"]


@pytest.fixture
def chat(tmp_path):
    now = [1000.0]
    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        party_wait=0.15,
        card_loader=lambda _: {},
    )
    with TestClient(app, base_url=ORIGIN) as client:
        sessions, mods = [], []
        finder = app.state.finder
        for index, uuid in enumerate(IDS):
            name = f"Player{index}"
            session = app.state.auth.issue("session", uuid, name, 3600)
            sessions.append({"Origin": ORIGIN, "Cookie": f"{COOKIE}={session}"})
            token = app.state.auth.issue("party", uuid, name, 3600, digest(session))
            mods.append({"Authorization": f"Bearer {token}"})
            finder.seen(uuid, name, "web")
            finder.set_stats(uuid, player_stats({}, []))
        party = finder.publish(IDS[0], "M7", "archer", list(CLASSES), False, {}, {})
        finder.reserve(IDS[1], party, "mage")
        yield client, finder, now, sessions, mods, party, app


def body(party, text="hello", request_id="a" * 16):
    return {"version": 1, "party_id": party, "text": text, "request_id": request_id}


def test_two_browsers_delivery_reconnect_and_retry_without_duplicates(chat):
    client, finder, _, sessions, _, party, _ = chat
    before = finder.personal(IDS[1])["state_version"]
    sent = client.post("/api/v1/party/chat", headers=sessions[0], json=body(party))
    assert sent.status_code == 200
    message = sent.json()["party"]["messages"][0]
    assert message == {
        "id": "1",
        "text": "hello",
        "at": 1_000_000,
        "sender": {"uuid": IDS[0], "name": "Player0"},
        "source": "web",
    }
    received = client.post(
        "/api/v1/party/state", headers=sessions[1], json={"version": 1, "known": before}
    ).json()
    assert received["party"]["messages"] == [message]
    retried = client.post("/api/v1/party/chat", headers=sessions[0], json=body(party)).json()
    assert retried["party"]["messages"] == [message]
    reloaded = client.post("/api/v1/party/state", headers=sessions[1], json={"version": 1}).json()
    assert reloaded["party"]["messages"] == [message]
    conflict = client.post("/api/v1/party/chat", headers=sessions[0], json=body(party, "changed"))
    assert conflict.status_code == 409
    assert "messages" not in finder.detail(finder.parties[party])


def test_chat_wakes_held_state_and_logout_during_wait_is_rechecked(chat, monkeypatch):
    client, finder, _, sessions, _, party, _ = chat
    waiting = Event()
    original = Waiters.wait

    async def wait(self, uuid, timeout):
        waiting.set()
        await original(self, uuid, timeout)

    monkeypatch.setattr(Waiters, "wait", wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.post,
            "/api/v1/party/state",
            headers=sessions[1],
            json={"version": 1, "known": finder.players[IDS[1]].version},
        )
        assert waiting.wait(2)
        client.post("/api/v1/party/chat", headers=sessions[0], json=body(party))
        assert pending.result(2).json()["party"]["messages"][0]["text"] == "hello"
        waiting.clear()
        pending = pool.submit(
            client.post,
            "/api/v1/party/state",
            headers=sessions[1],
            json={"version": 1, "known": finder.players[IDS[1]].version},
        )
        assert waiting.wait(2)
        client.post("/api/v1/auth/logout", headers=sessions[1], json={})
        assert pending.result(2).status_code == 401


def test_membership_origin_sender_and_logout_are_enforced(chat):
    client, finder, _, sessions, _, party, _ = chat
    endpoint = "/api/v1/party/chat"
    assert client.post(endpoint, json=body(party)).status_code == 403
    assert client.post(endpoint, headers={"Origin": ORIGIN}, json=body(party)).status_code == 401
    assert client.post(endpoint, headers=sessions[2], json=body(party)).status_code == 409
    assert (
        client.post(
            endpoint, headers=sessions[0], json={**body(party), "sender": IDS[1]}
        ).status_code
        == 422
    )
    client.post(endpoint, headers=sessions[0], json=body(party))
    client.post("/api/v1/party/remove", headers=sessions[0], json={"member": IDS[1], "block": True})
    assert client.post(endpoint, headers=sessions[1], json=body(party)).status_code == 409
    assert (
        client.post("/api/v1/party/state", headers=sessions[1], json={"version": 1}).json()["party"]
        is None
    )
    other = finder.publish(IDS[2], "F7", "mage", list(CLASSES), False, {}, {})
    assert client.post(endpoint, headers=sessions[2], json=body(party)).status_code == 409
    assert finder.personal(IDS[2])["party"]["messages"] == []
    assert other != party


@pytest.mark.parametrize(
    "text,code",
    [
        ("a" * 255, 200),
        ("a" * 256, 200),
        ("a" * 257, 422),
        ("", 422),
        ("  ", 422),
        ("hello\nworld", 422),
        ("\x00", 422),
        ("§khidden", 422),
        ("a\u202eb", 422),
        ("hello 👋", 200),
        ("<script>alert(1)</script>", 200),
    ],
    ids=[
        "below",
        "at",
        "above",
        "empty",
        "blank",
        "newline",
        "null",
        "format",
        "bidi",
        "emoji",
        "text",
    ],
)
def test_text_boundaries(chat, text, code):
    client, _, _, sessions, _, party, _ = chat
    assert (
        client.post("/api/v1/party/chat", headers=sessions[0], json=body(party, text)).status_code
        == code
    )


def test_per_account_rate_limit_and_retained_history_are_bounded(chat):
    client, finder, now, sessions, _, party, _ = chat
    for i in range(5):
        assert (
            client.post(
                "/api/v1/party/chat", headers=sessions[0], json=body(party, request_id=f"{i:016d}")
            ).status_code
            == 200
        )
    assert (
        client.post("/api/v1/party/chat", headers=sessions[0], json=body(party)).status_code == 429
    )
    now[0] += 5
    for i in range(5, 20):
        now[0] += 2
        finder.send_chat(IDS[0], party, f"{i:016d}", "hello", "web")
    now[0] += 5
    with pytest.raises(PartyError, match="chat_rate_limited"):
        finder.send_chat(IDS[0], party, "b" * 16, "hello", "web")
    # Slow, accepted traffic retains only the last 100 messages.
    for i in range(20, 125):
        now[0] += 61
        finder.send_chat(IDS[0], party, f"{i:016d}", "hello", "web")
    messages = finder.personal(IDS[0])["party"]["messages"]
    assert len(messages) == 100 and messages[0]["id"] == "26"
    assert len(finder.parties[party].chat.receipts) <= 11


def test_mod_chat_uses_scoped_credentials_and_loses_access_when_removed(chat):
    client, _, _, sessions, mods, party, _ = chat
    send = "/api/v1/party/mod/chat/send"
    read = "/api/v1/party/mod/chat/state"
    payload = {"version": 1, "party_id": party, "after": 0}
    assert client.post(send, headers=sessions[0], json=body(party)).status_code == 403
    assert (
        client.post(send, headers=mods[0], json=body(party)).json()["message"]["source"] == "game"
    )
    result = client.post(read, headers=mods[1], json=payload).json()
    assert result["latest"] == 1 and len(result["messages"]) == 1
    assert client.post(read, headers=mods[2], json=payload).status_code == 409
    client.post("/api/v1/party/leave", headers=sessions[1], json={})
    assert client.post(read, headers=mods[1], json=payload).status_code == 409
    client.post("/api/v1/auth/logout", headers=sessions[0], json={})
    assert client.post(read, headers=mods[0], json=payload).status_code == 401


def test_private_chat_survives_handoff_without_relisting_and_expires(chat):
    client, finder, now, sessions, _, party_id, _ = chat
    party = finder.parties[party_id]
    for uuid, role in zip(IDS[2:5], ("berserk", "healer", "tank"), strict=True):
        finder.reserve(uuid, party_id, role)
    finder.send_chat(IDS[0], party_id, "a" * 16, "hello", "web")
    finder.confirm_joined(IDS[0], party_id, IDS[:5])
    finder.confirm_joined(IDS[0], party_id, IDS[:5])
    assert finder.handoff(IDS[0]) is None
    assert finder.personal(IDS[0])["party"]["join_deadline"] is None
    finder.leave(IDS[1])
    assert party.completed and not finder.visible(party, finder.players[IDS[5]])
    assert (
        client.get("/api/v1/party/listings?floor=M7", headers=sessions[5]).json()["parties"] == []
    )
    assert client.get(f"/api/v1/party/listings/{party_id}", headers=sessions[5]).status_code == 404
    assert len(finder.personal(IDS[0])["party"]["messages"]) == 1
    finder.look(IDS[5], "M7", ["mage"], None)
    assert finder.players[IDS[5]].party is None
    now[0] += 61
    finder.sweep()
    assert party_id not in finder.parties
    assert all(finder.players[uuid].banned_until == 0 for uuid in IDS)


def test_one_hundred_parties_have_isolated_bounded_chat():
    finder = Finder(lambda: 1000)
    for index in range(100):
        members = [f"{index * 5 + slot:032x}" for slot in range(5)]
        for slot, uuid in enumerate(members):
            finder.seen(uuid, f"User{index}_{slot}", "web")
            finder.set_stats(uuid, player_stats({}, []))
        party = finder.publish(members[0], "M7", "archer", list(CLASSES), False, {}, {})
        for uuid, role in zip(members[1:], CLASSES[1:], strict=True):
            finder.reserve(uuid, party, role)
        finder.drain()
        finder.send_chat(members[0], party, "a" * 16, f"party {index}", "web")
        assert finder.drain() == set(members)
        for uuid in members:
            assert [m["text"] for m in finder.personal(uuid)["party"]["messages"]] == [
                f"party {index}"
            ]
    assert len(finder.parties) == 100
