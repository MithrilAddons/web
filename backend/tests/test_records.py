import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE
from mithril_web.records import RecordStore, Submission, with_mod_records

UUID = "0123456789abcdef0123456789abcdef"
OTHER = "f" * 32
ORIGIN = {"Origin": "https://mithril.foo"}
FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts/mod-records-v1.json").read_text()
)


@pytest.fixture
def setup(tmp_path):
    now = [1000.0]
    profile = {"id": UUID, "name": "TestPlayer"}
    app = create_app(
        database=tmp_path / "auth.db",
        clock=lambda: now[0],
        profile_lookup=lambda *_: profile.copy(),
        card_loader=lambda _: {
            "floors": [{"floor": "F7", "solo_clear_ms": None, "terminals_ms": None, "ss_ms": None}],
            "mod_records_available": False,
        },
    )
    with TestClient(app, base_url="https://mithril.foo") as client:
        proof = client.post(
            "/api/v1/auth/challenge", json={"version": 1, "uuid": UUID, "name": "TestPlayer"}
        ).json()
        link = client.post(
            "/api/v1/auth/verify", json={"challenge_id": proof["challenge_id"]}
        ).json()
        yield client, app, now, profile, link


def confirm(client, link):
    assert (
        client.post(
            "/api/v1/auth/complete",
            headers=ORIGIN,
            json={"token": link["link_token"], "remember": True},
        ).status_code
        == 200
    )


def challenge(client, link, uuid=UUID):
    return client.post(
        "/api/v1/auth/sync-challenge",
        json={
            "version": 1,
            "uuid": uuid,
            "name": "TestPlayer",
            "receipt_token": link["receipt_token"],
        },
    )


def authorize(client, link):
    proof = challenge(client, link).json()
    result = client.post(
        "/api/v1/auth/sync-verify",
        json={"challenge_id": proof["challenge_id"], "receipt_token": link["receipt_token"]},
    )
    assert result.status_code == 200
    return {"Authorization": "Bearer " + result.json()["sync_token"]}


def test_real_flow_requires_confirmation_and_separate_fresh_ownership(setup):
    client, app, _, profile, link = setup
    assert challenge(client, link).status_code == 401
    confirm(client, link)
    assert challenge(client, link, OTHER).status_code == 401
    proof = challenge(client, link).json()
    profile["id"] = OTHER
    body = {"challenge_id": proof["challenge_id"], "receipt_token": link["receipt_token"]}
    assert client.post("/api/v1/auth/sync-verify", json=body).status_code == 401
    profile["id"] = UUID
    assert client.post("/api/v1/auth/sync-verify", json=body).status_code == 410
    headers = authorize(client, link)
    assert (
        client.post("/api/v1/auth/sync-records", headers=headers, json=FIXTURE).json()["accepted"]
        == 4
    )
    card = client.get("/api/v1/auth/player-card").json()
    assert card["mod_records_available"]
    assert card["floors"][0]["solo_clear_ms"] == 300000
    assert card["floors"][0]["ss_ms"] is None
    assert app.state.records.read(OTHER) == []


def test_cookie_receipt_and_link_cannot_upload_and_origin_is_rejected(setup):
    client, _, _, _, link = setup
    confirm(client, link)
    for token in ("", link["receipt_token"], link["link_token"], client.cookies.get(COOKIE)):
        assert (
            client.post(
                "/api/v1/auth/sync-records",
                headers={"Authorization": "Bearer " + token},
                json=FIXTURE,
            ).status_code
            == 401
        )
    headers = authorize(client, link)
    assert (
        client.post(
            "/api/v1/auth/sync-records", headers={**headers, **ORIGIN}, json=FIXTURE
        ).status_code
        == 403
    )
    # Scoped sync credentials cannot sign into the browser or obtain a new receipt.
    client.cookies.set(COOKIE, headers["Authorization"][7:])
    assert not client.get("/api/v1/auth/session").json()["authenticated"]


@pytest.mark.parametrize("revocation", ["logout", "expiry", "session-expiry"])
def test_revocation_and_expiry_stop_uploads(setup, revocation):
    client, app, now, _, link = setup
    confirm(client, link)
    headers = authorize(client, link)
    if revocation == "logout":
        client.post("/api/v1/auth/logout", headers=ORIGIN)
    elif revocation == "expiry":
        now[0] += 900
    else:
        now[0] += 31 * 86400
    assert (
        client.post("/api/v1/auth/sync-records", headers=headers, json=FIXTURE).status_code == 401
    )
    assert app.state.records.read(UUID) == []


def test_challenge_scope_and_deadline(setup):
    client, _, now, _, link = setup
    confirm(client, link)
    proof = challenge(client, link).json()
    assert (
        client.post("/api/v1/auth/verify", json={"challenge_id": proof["challenge_id"]}).status_code
        == 410
    )
    now[0] += 60
    assert (
        client.post(
            "/api/v1/auth/sync-verify",
            json={"challenge_id": proof["challenge_id"], "receipt_token": link["receipt_token"]},
        ).status_code
        == 410
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("real_ms", 0),
        ("real_ms", 7200001),
        ("real_ms", True),
        ("real_ms", 1.5),
        ("ticks", 144001),
        ("ticks", -1),
        ("floor", "F6"),
        ("kind", "ss"),
    ],
)
def test_invalid_timings_are_rejected(setup, field, value):
    client, app, _, _, link = setup
    confirm(client, link)
    body = {"version": 1, "records": [{**FIXTURE["records"][0], field: value}]}
    assert (
        client.post(
            "/api/v1/auth/sync-records", headers=authorize(client, link), json=body
        ).status_code
        == 422
    )
    assert app.state.records.read(UUID) == []


def test_boundaries_duplicates_uuid_injection_and_request_size(setup):
    client, _, _, _, link = setup
    confirm(client, link)
    headers = authorize(client, link)
    for value in (1, 7200000):
        body = {
            "version": 1,
            "records": [{**FIXTURE["records"][0], "real_ms": value, "ticks": 144000}],
        }
        assert (
            client.post("/api/v1/auth/sync-records", headers=headers, json=body).status_code == 200
        )
    for body in (
        {**FIXTURE, "uuid": OTHER},
        {"version": 2, "records": FIXTURE["records"]},
        {"version": 1, "records": []},
        {"version": 1, "records": FIXTURE["records"] * 2},
        {"version": 1, "records": [FIXTURE["records"][0]] * 2},
    ):
        assert (
            client.post("/api/v1/auth/sync-records", headers=headers, json=body).status_code == 422
        )
    assert (
        client.post("/api/v1/auth/sync-records", headers=headers, content=" " * 4097).status_code
        == 413
    )


def test_persistence_idempotency_independent_minima_and_immutable_card(tmp_path):
    store = RecordStore(tmp_path / "records.db")
    records = Submission.model_validate(FIXTURE).records
    store.merge(UUID, records)
    store.merge(UUID, records)
    improved = records[0].model_copy(update={"real_ms": 290000, "ticks": 6000})
    store.merge(UUID, [improved])
    store.merge(UUID, records)  # Older clients cannot overwrite faster PBs.
    store.close()
    store = RecordStore(tmp_path / "records.db")
    result = store.read(UUID)
    assert len(result) == 4
    best = next(r for r in result if r["floor"] == "F7" and r["kind"] == "solo_clear")
    assert (best["real_ms"], best["ticks"]) == (290000, 5800)
    summary = {"floors": [{"floor": "F7", "solo_clear_ms": None}]}
    assert with_mod_records(summary, result)["floors"][0]["solo_clear_ms"] == 290000
    assert summary["floors"][0]["solo_clear_ms"] is None
    store.close()
