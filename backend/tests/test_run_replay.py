import base64
import copy
import json
import struct
from pathlib import Path

import pytest
from mithril_web.auth import COOKIE
from mithril_web.run_maps import MAP_LIMIT, RunMap
from mithril_web.run_replay import RunReplay
from pydantic import ValidationError
from test_record_evidence_api import api as api
from test_run_maps import complete, read, timed_map


def fixture():
    return json.loads((Path(__file__).parents[2] / "contracts/run-replay-v1.json").read_text())


def points():
    return list(struct.iter_unpack("<IhhBBH", base64.b64decode(fixture()["samples"])))


def encoded(values):
    return dict(
        version=1,
        samples=base64.b64encode(b"".join(struct.pack("<IhhBBH", *p) for p in values)).decode(),
    )


@pytest.mark.parametrize(
    "name",
    ["run-replay-v1.json", "run-replay-room-secrets-v1.json", "run-replay-teleports-v1.json"],
)
def test_shared_replay_retention(api, name):
    client, app, _, _, _ = api
    data = timed_map()
    data["replay"] = json.loads((Path(__file__).parents[2] / "contracts" / name).read_text())
    record = complete(api, data)["record_id"]
    assert read(client, record).json()["map"] == data
    # No replay payload is duplicated in retained progress evidence.
    assert all(
        "replay" not in row[0]
        for row in app.state.records.db.execute("SELECT body FROM solo_samples")
    )
    complete(api, ticks=294)
    assert read(client, record).json()["map"] is None
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0


def test_record_erasure_removes_replay_with_its_map(api):
    client, app, _, _, session = api
    data = timed_map()
    data["replay"] = fixture()
    record = complete(api, data)["record_id"]
    client.cookies.set(COOKIE, session)
    assert (
        client.post(
            "/api/v1/auth/erase",
            headers={"Origin": "https://mithril.foo"},
            json=dict(version=1, scope="records", confirmation="DELETE"),
        ).status_code
        == 200
    )
    assert read(client, record).status_code == 404
    assert app.state.records.db.execute("SELECT COUNT(*) FROM pb_maps").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [(0, 100), (1, -3201), (2, 0), (4, 4), (5, 3601)])
def test_replay_invalid_start_coordinates_flags_or_counters(field, value):
    changed = [list(point) for point in points()]
    changed[0][field] = value
    replay = RunReplay.model_validate(encoded(changed))
    with pytest.raises(ValueError):
        replay.validate_timeline(15000)


@pytest.mark.parametrize("flags", [5, 9, 13, 17, 73, 101, 105, 109, 113])
def test_teleport_kinds_and_saturated_counts(flags):
    changed = [list(point) for point in points()]
    changed[0][4] = 129
    changed[2][4] = flags
    RunReplay.model_validate(encoded(changed)).validate_timeline(15000)


@pytest.mark.parametrize(
    "index,flags",
    [
        (1, 128),
        (1, 129),
        (1, 21),
        (1, 25),
        (1, 29),
        (0, 5),
        (0, 133),
        (1, 4),
        (4, 7),
        (1, 32),
        (1, 65),
        (0, 161),
    ],
)
def test_rejects_reserved_or_misplaced_teleport_flags(index, flags):
    changed = [list(point) for point in points()]
    changed[index][4] = flags
    replay = RunReplay.model_validate(encoded(changed))
    with pytest.raises(ValueError, match="Invalid replay"):
        replay.validate_timeline(15000)


def test_capability_marker_accepts_unmapped_start_without_teleports():
    changed = [list(point) for point in points()]
    changed[0][1:3] = [0, 0]
    changed[0][4] = 131
    RunReplay.model_validate(encoded(changed)).validate_timeline(15000)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p[1].__setitem__(0, 0),
        lambda p: p[1].__setitem__(0, 199),
        lambda p: p[4].__setitem__(1, -2960),
        lambda p: p[4].__setitem__(4, 2),
        lambda p: p[5].__setitem__(5, 2),
        lambda p: p[-1].__setitem__(0, 15001),
        lambda p: p.pop(),
        lambda p: p[0].__setitem__(4, 0),
    ],
)
def test_replay_rejects_nonmonotonic_incomplete_or_invalid_timelines(change):
    changed = [list(point) for point in points()]
    change(changed)
    replay = RunReplay.model_validate(encoded(changed))
    with pytest.raises(ValueError):
        replay.validate_timeline(15000)


@pytest.mark.parametrize("raw", [b"x" * 25, b"x" * 12])
def test_replay_rejects_partial_or_single_samples(raw):
    data = timed_map()
    data["replay"] = dict(version=1, samples=base64.b64encode(raw).decode())
    with pytest.raises(ValueError):
        RunMap.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        lambda r: r.update(version=2),
        lambda r: r.update(samples="!" * 32),
        lambda r: r.update(samples="A" * (36002 * 16 + 1)),
        lambda r: r.update(images=[]),
    ],
)
def test_map_rejects_unknown_replay_schema_or_encoding(change):
    data = timed_map()
    data["replay"] = fixture()
    change(data["replay"])
    with pytest.raises(ValidationError):
        RunMap.model_validate(data)


def test_longest_replay_fits_request_storage_and_known_duration():
    data = timed_map()
    data["stats"].update(elapsed_ms=7_200_000, transit_ms=7_186_000)
    data["replay"] = encoded(
        (ms, -2960, -2960, 0, 1 if ms == 0 else 0, 0) for ms in range(0, 7_200_001, 200)
    )
    parsed = RunMap.model_validate(data)
    assert len(json.dumps(parsed.public_data()).encode()) < MAP_LIMIT < 640 * 1024
    changed = copy.deepcopy(data)
    changed["stats"].update(elapsed_ms=7_199_999, transit_ms=7_185_999)
    with pytest.raises(ValidationError):
        RunMap.model_validate(changed)


def room_events(events):
    return base64.b64encode(b"".join(struct.pack("<IBB", *e) for e in events)).decode()


@pytest.mark.parametrize(
    "events",
    [
        [(15001, 0, 1)],
        [(200, 1, 1)],
        [(200, 35, 1)],
        [(200, 0, 0)],
        [(200, 0, 4)],
        [(200, 7, 1)],
        [(200, 0, 1), (199, 0, 2)],
        [(200, 0, 1), (400, 0, 1)],
        [(200, 0, 2), (400, 0, 1)],
    ],
)
def test_invalid_room_counter_timeline(events):
    data = timed_map()
    data["replay"] = dict(fixture(), room_secrets=room_events(events))
    with pytest.raises(ValidationError):
        RunMap.model_validate(data)


@pytest.mark.parametrize("value", ["!", "AAAA", "A" * 28801, 2, []])
def test_room_counter_encoding_is_bounded_and_strict(value):
    data = timed_map()
    data["replay"] = dict(fixture(), room_secrets=value)
    with pytest.raises(ValidationError):
        RunMap.model_validate(data)


def test_empty_timeline_is_distinct_from_legacy_missing_timeline():
    data = timed_map()
    data["replay"] = dict(fixture(), room_secrets="")
    assert RunMap.model_validate(data).public_data()["replay"]["room_secrets"] == ""
    data["replay"] = fixture()
    assert "room_secrets" not in RunMap.model_validate(data).public_data()["replay"]


def test_room_counter_changes_allow_same_time_different_rooms_and_cutoff():
    data = timed_map()
    data["rooms"][1].update(secrets_found=2, secrets_total=2)
    data["stats"].update(secrets_found=5, secrets_total=7)
    data["replay"] = dict(
        fixture(), room_secrets=room_events([(200, 0, 1), (200, 7, 2), (15000, 0, 3)])
    )
    assert RunMap.model_validate(data).public_data()["replay"] == data["replay"]


def test_maximum_position_and_room_timelines_fit_storage_and_upload():
    data = timed_map()
    data["rooms"] = [
        dict(
            data["rooms"][0],
            tiles=[tile],
            secrets_found=100,
            secrets_total=100,
            elapsed_ms=0,
            ticks=0,
        )
        for tile in range(36)
    ]
    data["doors"] = []
    data["stats"].update(
        elapsed_ms=7_200_000,
        transit_ms=7_200_000,
        transit_ticks=300,
        secrets_found=3600,
        secrets_total=3600,
    )
    data["replay"] = encoded(
        (ms, -2960, -2960, 0, 1 if ms == 0 else 0, 0) for ms in range(0, 7_200_001, 200)
    )
    data["replay"]["room_secrets"] = room_events(
        (found * 200, tile, found) for found in range(1, 101) for tile in range(36)
    )
    parsed = RunMap.model_validate(data).public_data()
    assert len(json.dumps(parsed).encode()) < MAP_LIMIT < 640 * 1024
