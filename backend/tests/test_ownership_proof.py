import hashlib

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app

UUID = "0" * 32
NONCE = "1" * 64


@pytest.mark.parametrize("scope", ["link", "sync", "party"])
def test_client_bound_proof_is_fresh_scoped_and_single_use(tmp_path, scope):
    lookups = []
    app = create_app(
        database=tmp_path / "auth.sqlite3",
        profile_lookup=lambda name, server_id: (
            lookups.append((name, server_id)) or {"id": UUID, "name": name}
        ),
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        body = {"version": 1, "uuid": UUID, "name": "Player", "client_nonce": NONCE}
        verify = {}
        if scope != "link":
            store = app.state.auth
            link, receipt, _ = store.issue_link(UUID, "Player")
            store.finish_link(link, "", remember=True)
            body["receipt_token"] = receipt
            verify["receipt_token"] = receipt
        prefix = "" if scope == "link" else scope + "-"
        path = f"/api/v1/auth/{prefix}challenge"
        first = client.post(path, json=body)
        assert first.status_code == 200
        proof = first.json()
        value = f"mithrilpf:ownership:v2:{scope}:{UUID}:{NONCE}:{proof['server_nonce']}"
        expected = hashlib.sha256(value.encode()).hexdigest()[:39]
        assert proof["server_id"] == expected
        assert len(proof["server_nonce"]) == 64
        second = client.post(path, json=body).json()
        assert second["server_id"] != expected
        assert second["server_nonce"] != proof["server_nonce"]
        verify["challenge_id"] = proof["challenge_id"]
        assert client.post(f"/api/v1/auth/{prefix}verify", json=verify).status_code == 200
        assert lookups == [("Player", expected)]
        assert client.post(f"/api/v1/auth/{prefix}verify", json=verify).status_code == 410
        assert len(lookups) == 1


@pytest.mark.parametrize("nonce", ["", "a" * 63, "A" * 64, "https://example.invalid", 1])
def test_invalid_client_nonce_is_rejected_before_issuing_proof(tmp_path, nonce):
    app = create_app(database=tmp_path / "auth.sqlite3")
    with TestClient(app, base_url="https://mithril.foo") as client:
        response = client.post(
            "/api/v1/auth/challenge",
            json={"version": 1, "uuid": UUID, "name": "Player", "client_nonce": nonce},
        )
        assert response.status_code == 422
