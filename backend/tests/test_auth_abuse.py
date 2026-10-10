"""Anonymous auth limits use fake peers, clocks and ownership replies; no live services."""

import threading
from concurrent.futures import ThreadPoolExecutor
from ipaddress import IPv4Address

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import DAY, AuthAttempts, digest

UUID = "0123456789abcdef0123456789abcdef"
BODY = {"version": 1, "uuid": UUID, "name": "TestPlayer"}


@pytest.mark.parametrize("per_client", [10, 20])
def test_client_boundary_retry_and_expiry(per_client):
    now = [0.0]
    attempts = AuthAttempts(per_client, 300, clock=lambda: now[0])
    for _ in range(per_client - 1):
        attempts.check("192.0.2.1")
    attempts.check("192.0.2.1")
    with pytest.raises(HTTPException) as failure:
        attempts.check("192.0.2.1")
    assert failure.value.status_code == 429
    assert failure.value.headers == {"Retry-After": "60"}
    attempts.check("192.0.2.2")
    now[0] = 59.1
    with pytest.raises(HTTPException) as failure:
        attempts.check("192.0.2.1")
    assert failure.value.headers == {"Retry-After": "1"}
    now[0] = 60
    attempts.check("192.0.2.1")
    assert len(attempts.attempts) == 1


def test_global_budget_bounds_memory_even_when_rejected_peers_keep_changing():
    now = [0]
    attempts = AuthAttempts(10, 300, clock=lambda: now[0])
    for i in range(299):
        attempts.check(str(IPv4Address(0xC0000200 + i)))
    attempts.check("198.51.100.1")
    for i in range(1000):
        peer = str(IPv4Address(0xC6336400 + i))
        with pytest.raises(HTTPException) as failure:
            attempts.check(peer)
        assert failure.value.status_code == 429
    assert len(attempts.attempts) == 300
    now[0] = 60
    attempts.check("198.51.100.1")
    assert len(attempts.attempts) == 1


@pytest.mark.parametrize("same_peer,expected", [(True, 10), (False, 12)])
def test_concurrent_requests_cannot_overrun_either_budget(same_peer, expected):
    attempts = AuthAttempts(10, 12, clock=lambda: 0)

    def request(i):
        try:
            attempts.check("192.0.2.1" if same_peer else f"192.0.2.{i + 1}")
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(16) as pool:
        assert sum(pool.map(request, range(32))) == expected
    assert len(attempts.attempts) == expected


@pytest.mark.parametrize(
    "first,alias,separate",
    [
        ("2001:db8:1:2::1", "2001:db8:1:2::abcd", "2001:db8:1:3::1"),
        ("192.0.2.1", "::ffff:192.0.2.1", "192.0.2.2"),
    ],
)
def test_address_aliases_share_the_same_budget(first, alias, separate):
    attempts = AuthAttempts(10, 300, clock=lambda: 0)
    for _ in range(10):
        attempts.check(first)
    with pytest.raises(HTTPException):
        attempts.check(alias)
    attempts.check(separate)


@pytest.fixture
def auth(tmp_path):
    now, lookups = [1000000.0], []

    def lookup(*args):
        lookups.append(args)
        return {"id": UUID, "name": BODY["name"]}

    app = create_app(database=tmp_path / "auth.db", clock=lambda: now[0], profile_lookup=lookup)
    with TestClient(app, base_url="https://mithril.foo", client=("192.0.2.1", 1234)) as client:
        yield client, now, lookups


def test_challenge_abuse_cannot_bypass_limit_with_identity_or_forwarding_headers(auth):
    client, now, lookups = auth
    issued = []
    for i in range(10):
        result = client.post("/api/v1/auth/challenge", json={**BODY, "uuid": f"{i:032x}"})
        assert result.status_code == 200
        issued.append(result.json()["challenge_id"])
    for i in range(15):
        result = client.post(
            "/api/v1/auth/challenge",
            json={**BODY, "uuid": f"{i + 100:032x}"},
            headers={"X-Forwarded-For": f"192.0.2.{i + 2}", "X-Real-IP": f"192.0.2.{i + 2}"},
        )
        assert result.status_code == 429
        assert result.headers["Retry-After"] == "60"
    store = client.app.state.auth
    assert store.db.execute("SELECT COUNT(*) FROM auth").fetchone()[0] == 10
    assert all(store.get(token, "challenge") for token in issued)
    assert not lookups
    now[0] += 60
    assert client.post("/api/v1/auth/challenge", json=BODY).status_code == 200
    assert store.db.execute("SELECT COUNT(*) FROM auth").fetchone()[0] == 1


def test_distributed_challenges_stay_below_store_capacity_and_recover(auth):
    client, now, lookups = auth
    for i in range(30):
        peer = TestClient(
            client.app, base_url="https://mithril.foo", client=(f"198.51.100.{i + 1}", 1234)
        )
        try:
            for _ in range(10):
                assert peer.post("/api/v1/auth/challenge", json=BODY).status_code == 200
        finally:
            peer.close()
    assert client.post("/api/v1/auth/challenge", json=BODY).status_code == 429
    assert client.app.state.auth.db.execute("SELECT COUNT(*) FROM auth").fetchone()[0] == 300
    assert not lookups
    now[0] += 60
    assert client.post("/api/v1/auth/challenge", json=BODY).status_code == 200


def test_invalid_verify_attempts_are_limited_without_consuming_a_valid_challenge(auth):
    client, now, lookups = auth
    token = client.post("/api/v1/auth/challenge", json=BODY).json()["challenge_id"]
    now[0] += 1
    for _ in range(20):
        assert (
            client.post("/api/v1/auth/verify", json={"challenge_id": "x" * 43}).status_code == 410
        )
    result = client.post("/api/v1/auth/verify", json={"challenge_id": token})
    assert result.status_code == 429
    assert client.app.state.auth.get(token, "challenge")
    assert not lookups
    # The challenge can expire while waiting: the client creates a new one after the cooldown.
    now[0] += 60
    token = client.post("/api/v1/auth/challenge", json=BODY).json()["challenge_id"]
    assert client.post("/api/v1/auth/verify", json={"challenge_id": token}).status_code == 200
    assert len(lookups) == 1


def test_lookup_failures_count_towards_verification_budget(auth):
    client, _, lookups = auth
    store = client.app.state.auth
    for _ in range(20):
        token = store.issue("challenge", "f" * 32, "DifferentPlayer", 60, "fake-server")
        assert client.post("/api/v1/auth/verify", json={"challenge_id": token}).status_code == 401
    token = store.issue("challenge", UUID, BODY["name"], 60, "fake-server")
    assert client.post("/api/v1/auth/verify", json={"challenge_id": token}).status_code == 429
    assert len(lookups) == 20


@pytest.mark.parametrize("scope", ["sync", "party"])
def test_linked_proofs_work_while_anonymous_lookups_are_busy(tmp_path, scope):
    release, busy = threading.Event(), threading.Event()
    lock = threading.Lock()
    started = []

    def lookup(name, server_id):
        if server_id == "slow-anonymous":
            with lock:
                started.append(name)
                if len(started) == 2:
                    busy.set()
            assert release.wait(5), "test lookup was not released"
        return {"id": UUID, "name": BODY["name"]}

    app = create_app(database=tmp_path / "auth.db", profile_lookup=lookup)
    with TestClient(app, base_url="https://mithril.foo") as client, ThreadPoolExecutor(2) as pool:
        store = app.state.auth
        session = store.issue("session", UUID, BODY["name"], DAY)
        receipt = store.issue("receipt", UUID, BODY["name"], DAY, digest(session), remembered=True)
        tokens = [
            store.issue("challenge", UUID, BODY["name"], 60, "slow-anonymous") for _ in range(3)
        ]
        futures = [
            pool.submit(client.post, "/api/v1/auth/verify", json={"challenge_id": token})
            for token in tokens[:2]
        ]
        try:
            assert busy.wait(5)
            rejected = client.post("/api/v1/auth/verify", json={"challenge_id": tokens[2]})
            assert rejected.status_code == 503
            assert rejected.headers["Retry-After"] == "1"
            assert store.get(tokens[2], "challenge")  # Capacity rejection does not burn the proof.
            proof = client.post(
                f"/api/v1/auth/{scope}-challenge", json={**BODY, "receipt_token": receipt}
            )
            assert proof.status_code == 200
            result = client.post(
                f"/api/v1/auth/{scope}-verify",
                json={"challenge_id": proof.json()["challenge_id"], "receipt_token": receipt},
            )
            assert result.status_code == 200
        finally:
            release.set()
        assert all(future.result().status_code == 200 for future in futures)
        assert (
            client.post("/api/v1/auth/verify", json={"challenge_id": tokens[2]}).status_code == 200
        )


@pytest.mark.parametrize("scope", ["sync", "party"])
def test_unlinked_scoped_attempt_never_uses_reserved_lookup_capacity(auth, scope):
    client, _, lookups = auth
    store = client.app.state.auth
    token = store.issue(f"{scope}_challenge", UUID, BODY["name"], 60, "fake-server")
    result = client.post(
        f"/api/v1/auth/{scope}-verify",
        json={"challenge_id": token, "receipt_token": "x" * 43},
    )
    assert result.status_code == 401
    assert store.get(token, f"{scope}_challenge")
    assert not lookups
