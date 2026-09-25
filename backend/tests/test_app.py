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
