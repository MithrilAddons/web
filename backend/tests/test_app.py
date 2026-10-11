import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(database=tmp_path / "auth.db"), base_url="http://localhost"
    ) as value:
        yield value


def test_health_matches_shared_contract(client):
    expected = json.loads((Path(__file__).parents[2] / "contracts/health-v1.json").read_text())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/api/v1/parties", "/api/v1/login"])
def test_unimplemented_endpoints_are_not_exposed(client, path):
    assert client.get(path).status_code == 404


def test_health_is_read_only(client):
    assert client.post("/api/v1/health").status_code == 405


def test_untrusted_host_is_rejected(client):
    assert client.get("/api/v1/health", headers={"Host": "untrusted.invalid"}).status_code == 400


def test_no_cross_origin_access_is_granted(client):
    response = client.get("/api/v1/health", headers={"Origin": "https://untrusted.invalid"})
    assert "access-control-allow-origin" not in response.headers


def test_a_full_process_answers_busy_at_once(client):
    app = client.app
    app.state.in_flight = app.state.max_in_flight
    busy = client.get("/api/v1/games/curator/leaderboard")
    assert busy.status_code == 503
    assert busy.headers["retry-after"] == "5"
    assert busy.headers["cache-control"] == "no-store"
    assert busy.json() == {"detail": "mithril.foo is busy. Try again in a few seconds."}
    # Health stays answerable and held party reads are not counted.
    assert client.get("/api/v1/health").status_code == 200
    assert client.post("/api/v1/party/state", json={}).status_code != 503
    app.state.in_flight -= 1
    assert client.get("/api/v1/games/curator/leaderboard").status_code == 200
    assert app.state.in_flight == app.state.max_in_flight - 1


def test_requests_release_their_slot_even_when_they_fail(client):
    assert client.get("/api/v1/games/curator/leaderboard").status_code == 200
    assert client.post("/api/v1/auth/session", content=b"x" * 5000).status_code == 413
    assert client.get("/api/v1/does-not-exist").status_code == 404
    assert client.app.state.in_flight == 0
