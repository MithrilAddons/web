import copy
import json
import zlib

import pytest
from mithril_web.auth import COOKIE
from mithril_web.leaderboards import snapshot
from mithril_web.run_maps import MAP_LIMIT, RunMap, retain_current
from pydantic import ValidationError
from test_moderation import MOD, USER, post, seed
from test_moderation import setup as setup
from test_record_evidence import HIGH, LOW, UUID
from test_record_evidence_api import api as api
from test_record_evidence_api import start_body


def map_data():
    return dict(
        version=1,
        rooms=[
            dict(
                tiles=[0, 1],
                name="Synthetic room",
                type="NORMAL",
                state="CLEARED",
                secrets_found=3,
                secrets_total=5,
            ),
            dict(
                tiles=[7],
                name="Puzzle",
                type="PUZZLE",
                state="COMPLETE",
                secrets_found=0,
                secrets_total=0,
            ),
        ],
        doors=[dict(a=1, b=7, type="NORMAL")],
    )


def complete(api, data=None, ticks=300, dead=False):
    client, _, now, headers, _ = api
    attempt = client.post("/api/v1/records/solo-start", headers=headers, json=start_body()).json()
    for seq in range(1, 4):
        now[0] += 5
        body = dict(
            version=2,
            attempt_id=attempt["attempt_id"],
            nonce=attempt["nonce"],
            sequence=seq,
            elapsed_ms=seq * 5000,
            ticks=ticks * seq // 3,
            roster=[UUID],
            dead=dead and seq == 3,
            valid=True,
            evidence=HIGH if seq == 3 else LOW,
            complete=seq == 3,
        )
        if seq == 3 and data is not None:
            body["map"] = data
        response = client.post("/api/v1/records/solo-progress", headers=headers, json=body)
        assert response.status_code == 200, response.text
        attempt = response.json()
    return attempt


def read(client, record):
    return client.get(f"/api/v1/records/solo/{record}")


def test_completion_retains_only_current_best_and_does_not_duplicate_map_in_evidence(api):
    client, app, now, _, _ = api
    first = complete(api, map_data())["record_id"]
    response = read(client, first)
    assert response.status_code == 200
    assert response.json()["map"] == map_data()
    assert response.json()["record"]["uuid"] == UUID
    assert snapshot(app.state.records, app.state.auth)["boards"]["f7_solo"][0]["map_id"] == first
    for row in app.state.records.db.execute("SELECT body FROM solo_samples"):
        assert "map" not in json.loads(row[0])
    now[0] += 1
    slower = complete(api, map_data(), ticks=306)["record_id"]
    assert read(client, slower).json()["map"] is None
    assert read(client, first).json()["map"] == map_data()
    now[0] += 1
    equal = complete(api, map_data())["record_id"]
    assert read(client, equal).json()["map"] is None
    faster = complete(api, map_data(), ticks=294)["record_id"]
    assert read(client, first).json()["map"] is None
    assert read(client, faster).json()["map"] == map_data()
    # An older client beating this time must not leave a map from the wrong run.
    newest = complete(api, ticks=288)["record_id"]
    assert read(client, newest).json()["map"] is None
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0


def test_rejected_attempt_and_noncompletion_cannot_retain_maps(api):
    client, app, _, headers, _ = api
    assert complete(api, map_data(), dead=True)["status"] == "rejected"
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0
    body = dict(
        version=2,
        attempt_id="a" * 43,
        nonce="b" * 43,
        sequence=1,
        elapsed_ms=5000,
        ticks=100,
        roster=[UUID],
        dead=False,
        valid=True,
        evidence=LOW,
        complete=False,
        map=map_data(),
    )
    assert (
        client.post("/api/v1/records/solo-progress", headers=headers, json=body).status_code == 422
    )


def test_privacy_erasure_removes_maps(api):
    client, app, _, _, session = api
    record = complete(api, map_data())["record_id"]
    client.cookies.set(COOKIE, session)
    response = client.post(
        "/api/v1/auth/erase",
        headers={"Origin": "https://mithril.foo"},
        json=dict(version=1, scope="records", confirmation="DELETE"),
    )
    assert response.status_code == 200
    assert read(client, record).status_code == 404
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0


def test_bans_hide_maps_and_invalidation_permanently_retires_them(setup):
    client, app, _, headers, _ = setup
    record = seed(app)
    with app.state.records.db:
        retain_current(app.state.records.db, USER, "F7", record, RunMap.model_validate(map_data()))
    assert read(client, record).status_code == 200
    assert post(client, headers[MOD], "sanction", uuid=USER, kind="ban").status_code == 200
    assert read(client, record).status_code == 404
    assert (
        post(
            client,
            headers[MOD],
            "record",
            record_id=record,
            expected_status="eligible",
            action="invalidate",
        ).status_code
        == 200
    )
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(version=2),
        lambda m: m.update(pixels=[]),
        lambda m: m["rooms"][0].update(tiles=[0, 0]),
        lambda m: m["rooms"][0].update(tiles=[5, 6]),
        lambda m: m["rooms"][0].update(tiles=[-1]),
        lambda m: m["rooms"][0].update(tiles=[36]),
        lambda m: m["rooms"][0].update(tiles=[0, 1, 2, 3, 4]),
        lambda m: m["rooms"][0].update(secrets_found=6),
        lambda m: m["rooms"][0].update(secrets_total=True),
        lambda m: m["rooms"][0].update(name="x" * 65),
        lambda m: m["rooms"][1].update(tiles=[1]),
        lambda m: m["doors"].append(copy.deepcopy(m["doors"][0])),
        lambda m: m["doors"][0].update(a=7, b=1),
        lambda m: m["doors"][0].update(b=8),
        lambda m: m["doors"][0].update(a=0, b=1),
        lambda m: m["doors"][0].update(a=7, b=13),
    ],
)
def test_map_validation(change):
    data = map_data()
    change(data)
    with pytest.raises(ValidationError):
        RunMap.model_validate(data)


def test_public_reader_rejects_unknown_ids_and_bounded_decompression(api):
    client, app, _, _, _ = api
    assert read(client, "invalid").status_code == 404
    assert read(client, "a" * 43).status_code == 404
    record = complete(api, map_data())["record_id"]
    with app.state.records.db:
        app.state.records.db.execute(
            "UPDATE pb_maps SET data=?", (zlib.compress(b" " * (MAP_LIMIT + 1)),)
        )
    assert read(client, record).status_code == 503


def test_larger_body_allowance_is_confined_to_solo_progress(api):
    client, _, _, headers, _ = api
    padding = " " * 5000
    # Whitespace is valid JSON padding, but does not make an invalid body valid.
    response = client.post("/api/v1/records/solo-progress", headers=headers, content=padding + "{}")
    assert response.status_code == 422
    assert (
        client.post(
            "/api/v1/records/solo-start",
            headers=headers,
            content=padding + json.dumps(start_body()),
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/api/v1/records/solo-progress", headers=headers, content=" " * 32769
        ).status_code
        == 413
    )
