from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from test_record_evidence import HIGH, LOW, UUID


@pytest.fixture
def api(tmp_path):
    now = [1000.0]
    app = create_app(database=tmp_path / "auth.db", clock=lambda: now[0])
    with TestClient(app, base_url="https://mithril.foo") as client:
        store = app.state.auth
        session = store.issue("session", UUID, "SyntheticPlayer", DAY)
        parent = store.get(session, "session")["token"]
        token = store.issue("sync", UUID, "SyntheticPlayer", 900, server_id=parent)
        yield client, app, now, {"Authorization": f"Bearer {token}"}, session


def start_body():
    return dict(version=2, floor="F7", elapsed_ms=0, ticks=0, paul=False)


def test_api_authentication_scope_origin_and_expiry(api):
    client, _, now, headers, session = api
    path = "/api/v1/records/solo-start"
    assert client.post(path, json=start_body()).status_code == 401
    assert (
        client.post(
            path, json=start_body(), headers={"Authorization": f"Bearer {session}"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            path, json=start_body(), headers={**headers, "Origin": "https://mithril.foo"}
        ).status_code
        == 403
    )
    assert client.post(path, json=start_body(), headers=headers).status_code == 200
    now[0] += 900
    assert client.post(path, json=start_body(), headers=headers).status_code == 401


def test_finish_refreshes_matching_stats_and_logout_revokes_tracking(api):
    client, app, now, headers, session = api
    app.state.records_changed = AsyncMock()
    attempt = client.post("/api/v1/records/solo-start", headers=headers, json=start_body()).json()
    for seq in range(1, 4):
        now[0] += 5
        payload = dict(
            version=2,
            attempt_id=attempt["attempt_id"],
            nonce=attempt["nonce"],
            sequence=seq,
            elapsed_ms=seq * 5000,
            ticks=seq * 100,
            roster=[UUID],
            dead=False,
            valid=True,
            evidence=HIGH if seq == 3 else LOW,
            complete=seq == 3,
        )
        response = client.post("/api/v1/records/solo-progress", headers=headers, json=payload)
        assert response.status_code == 200
        attempt = response.json()
    assert attempt["status"] == "accepted"
    app.state.records_changed.assert_awaited_once_with(UUID)
    client.cookies.set(COOKIE, session)
    assert (
        client.post("/api/v1/auth/logout", headers={"Origin": "https://mithril.foo"}).status_code
        == 200
    )
    assert (
        client.post("/api/v1/records/solo-start", headers=headers, json=start_body()).status_code
        == 401
    )


def test_legacy_route_cannot_create_untracked_records(api):
    client, app, _, headers, _ = api
    response = client.post(
        "/api/v1/auth/sync-records",
        headers=headers,
        json={"version": 1, "records": [dict(floor="F7", kind="solo_clear", real_ms=1, ticks=1)]},
    )
    assert response.status_code == 410
    assert app.state.records.read(UUID) == []
