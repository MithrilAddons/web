from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY, AuthStore

UUID = "0123456789abcdef0123456789abcdef"
NAME = "TestPlayer"
ORIGIN = {"Origin": "https://mithril.foo"}


@pytest.fixture
def auth(tmp_path):
    now = [1000000.0]
    profile = {"id": UUID, "name": NAME}
    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        profile_lookup=lambda name, server_id: profile.copy(),
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        yield client, now, profile


def challenge(client):
    result = client.post("/api/v1/auth/challenge", json={"version": 1, "uuid": UUID, "name": NAME})
    assert result.status_code == 200
    assert len(result.json()["server_id"]) == 39
    assert "set-cookie" not in result.headers
    return result.json()["challenge_id"]


def link(client):
    result = client.post("/api/v1/auth/verify", json={"challenge_id": challenge(client)})
    assert result.status_code == 200
    return result.json()["link_token"]


def complete(client, token, remember=True):
    return client.post(
        "/api/v1/auth/complete", headers=ORIGIN, json={"token": token, "remember": remember}
    )


def test_full_flow_cookie_replay_and_logout(auth):
    client, _, _ = auth
    anonymous = client.get("/api/v1/auth/session")
    assert anonymous.json() == {"authenticated": False}
    assert "set-cookie" not in anonymous.headers
    token = link(client)
    for _ in range(2):
        preview = client.post("/api/v1/auth/preview", headers=ORIGIN, json={"token": token})
        assert preview.json() == {"uuid": UUID, "name": NAME}
        assert "set-cookie" not in preview.headers
    result = complete(client, token)
    cookie = result.headers["set-cookie"]
    for expected in ("Secure", "HttpOnly", "SameSite=strict", "Path=/", "Max-Age=2592000"):
        assert expected in cookie
    assert "Domain=" not in cookie
    assert complete(client, token).status_code == 410
    assert client.get("/api/v1/auth/session").json()["user"]["name"] == NAME
    old = client.cookies.get(COOKIE)
    assert client.post("/api/v1/auth/logout", headers=ORIGIN, json={}).status_code == 200
    assert client.get("/api/v1/auth/session", headers={"Cookie": f"{COOKIE}={old}"}).json() == {
        "authenticated": False
    }


def test_session_cookie_and_expiration(auth):
    client, now, _ = auth
    result = complete(client, link(client), False)
    assert "Max-Age" not in result.headers["set-cookie"]
    now[0] += DAY
    assert not client.get("/api/v1/auth/session").json()["authenticated"]


def test_remembered_session_renews_and_replacement_revokes_old(auth):
    client, now, _ = auth
    complete(client, link(client))
    old = client.cookies.get(COOKIE)
    now[0] += DAY + 1
    assert "Max-Age" in client.get("/api/v1/auth/session").headers["set-cookie"]
    complete(client, link(client))
    assert not client.get("/api/v1/auth/session", headers={"Cookie": f"{COOKIE}={old}"}).json()[
        "authenticated"
    ]


@pytest.mark.parametrize("kind,seconds", [("challenge", 60), ("link", 300)])
def test_deadlines_are_exclusive(auth, kind, seconds):
    client, now, _ = auth
    token = challenge(client) if kind == "challenge" else link(client)
    now[0] += seconds
    response = (
        client.post("/api/v1/auth/verify", json={"challenge_id": token})
        if kind == "challenge"
        else complete(client, token)
    )
    assert response.status_code == 410


def test_claimed_identity_is_not_enough_and_failed_proof_is_consumed(auth):
    client, _, profile = auth
    token = challenge(client)
    profile["id"] = "f" * 32
    assert client.post("/api/v1/auth/verify", json={"challenge_id": token}).status_code == 401
    profile["id"] = UUID
    assert client.post("/api/v1/auth/verify", json={"challenge_id": token}).status_code == 410


@pytest.mark.parametrize("name", ["DifferentName", None, 12])
def test_wrong_or_malformed_profile_name_is_rejected(auth, name):
    client, _, profile = auth
    profile["name"] = name
    assert (
        client.post("/api/v1/auth/verify", json={"challenge_id": challenge(client)}).status_code
        == 401
    )


def test_browser_origin_required_before_consuming_link(auth):
    client, _, _ = auth
    token = link(client)
    body = {"token": token, "remember": True}
    assert client.post("/api/v1/auth/complete", json=body).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/complete", json=body, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )
    assert complete(client, token).status_code == 200
    assert client.post("/api/v1/auth/logout", json={}).status_code == 403


def test_bounds_and_mod_origin(auth):
    client, _, _ = auth
    body = {"version": 1, "uuid": UUID, "name": NAME}
    assert client.post("/api/v1/auth/challenge", json=body, headers=ORIGIN).status_code == 403
    assert (
        client.post("/api/v1/auth/challenge", json={**body, "access_token": "fake"}).status_code
        == 422
    )
    assert client.post("/api/v1/auth/challenge", content="x" * 4097).status_code == 413
    assert (
        client.post("/api/v1/auth/preview", headers=ORIGIN, json={"token": "x"}).status_code == 422
    )


def test_store_persistence_hashing_and_atomic_consumption(tmp_path):
    path = tmp_path / "auth.db"
    store = AuthStore(path, clock=lambda: 100)
    token = store.issue("link", UUID, NAME, 300)
    session = store.issue("session", UUID, NAME, DAY)
    assert token.encode() not in path.read_bytes()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: store.get(token, "link", consume=True), range(8)))
    assert sum(result is not None for result in results) == 1
    store.close()
    store = AuthStore(path, clock=lambda: 200)
    assert store.get(session, "session")["uuid"] == UUID
    store.close()


def test_lookup_failure_does_not_leak_details(tmp_path):
    def lookup(*args):
        raise OSError("private response")

    with TestClient(
        create_app(database=tmp_path / "auth.db", profile_lookup=lookup),
        base_url="https://mithril.foo",
    ) as client:
        response = client.post("/api/v1/auth/verify", json={"challenge_id": challenge(client)})
        assert response.status_code == 401
        assert "private response" not in response.text


def receipt_link(client):
    return client.post("/api/v1/auth/verify", json={"challenge_id": challenge(client)}).json()


def status(client, receipt):
    response = client.post("/api/v1/auth/link-status", json={"token": receipt})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    return response.json()


def test_receipt_confirms_only_after_browser_and_cannot_sign_in(auth):
    client, _, _ = auth
    issued = receipt_link(client)
    receipt = issued["receipt_token"]
    assert receipt != issued["link_token"]
    assert status(client, receipt) == {"version": 1, "status": "pending"}
    assert complete(client, receipt).status_code == 410
    assert not client.get("/api/v1/auth/session", headers={"Cookie": f"{COOKIE}={receipt}"}).json()[
        "authenticated"
    ]
    assert status(client, issued["link_token"])["status"] == "expired"
    assert complete(client, issued["link_token"]).status_code == 200
    assert status(client, receipt) == {
        "version": 1,
        "status": "linked",
        "user": {"uuid": UUID, "name": NAME},
    }
    client.post("/api/v1/auth/logout", headers=ORIGIN, json={})
    assert status(client, receipt)["status"] == "expired"


def test_receipt_expiry_renewal_and_session_replacement(auth):
    client, now, _ = auth
    pending = receipt_link(client)
    now[0] += 300
    assert status(client, pending["receipt_token"])["status"] == "expired"
    issued = receipt_link(client)
    complete(client, issued["link_token"], False)
    now[0] += DAY
    assert status(client, issued["receipt_token"])["status"] == "expired"
    issued = receipt_link(client)
    complete(client, issued["link_token"])
    now[0] += 29 * DAY
    client.get("/api/v1/auth/session")
    now[0] += 2 * DAY
    assert status(client, issued["receipt_token"])["status"] == "linked"
    complete(client, link(client))
    assert status(client, issued["receipt_token"])["status"] == "expired"


def test_receipt_status_is_mod_only_and_does_not_accept_identity(auth):
    client, _, _ = auth
    issued = receipt_link(client)
    assert (
        client.post(
            "/api/v1/auth/link-status", headers=ORIGIN, json={"token": issued["receipt_token"]}
        ).status_code
        == 403
    )
    assert client.post("/api/v1/auth/link-status", json={"uuid": UUID}).status_code == 422
    assert status(client, "z" * 43) == {"version": 1, "status": "expired"}


def test_confirmed_receipt_survives_store_restart(tmp_path):
    path = tmp_path / "auth.db"
    store = AuthStore(path, clock=lambda: 100)
    from mithril_web.auth import digest

    link_token = store.issue("link", UUID, NAME, 300)
    receipt = store.issue("receipt", UUID, NAME, 300, server_id=digest(link_token))
    session = store.issue("session", UUID, NAME, DAY)
    store.confirm_receipts(link_token, session)
    store.close()
    store = AuthStore(path, clock=lambda: 200)
    assert store.receipt_status(receipt)["status"] == "linked"
    assert receipt.encode() not in path.read_bytes()
    store.close()
