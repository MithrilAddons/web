import json
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE
from mithril_web.player_card import (
    CATACOMBS_XP,
    MAX_RESPONSE,
    PlayerCardCache,
    catacombs_level,
    fetch_card,
    parse_profiles,
)

UUID = "0123456789abcdef0123456789abcdef"
PROFILE_ID = "1" * 32


def payload():
    return {
        "success": True,
        "profiles": [
            {
                "selected": True,
                "profile_id": PROFILE_ID,
                "cute_name": "Apple",
                "members": {
                    UUID: {
                        "dungeons": {
                            "secrets": 12345,
                            "dungeon_types": {
                                "catacombs": {
                                    "experience": 97559640,
                                    "fastest_time_s_plus": {"7": 260000},
                                },
                                "master_catacombs": {"fastest_time_s_plus": {"7": 290000}},
                            },
                        },
                        "accessory_bag_storage": {"highest_magical_power": 1000},
                    }
                },
            }
        ],
    }


def test_shared_contract_and_selected_profile_not_highest_xp():
    data = payload()
    data["profiles"].insert(
        0, {"selected": False, "members": {UUID: {"dungeons": {"secrets": 99999}}}}
    )
    result = parse_profiles(data, UUID)
    expected = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts/player-card-v1.json").read_text()
    )
    for name in ("version", "user", "fetched_at"):
        expected.pop(name)
    assert result == expected


def test_xp_curve_every_level_boundary_and_overflow():
    assert sum(CATACOMBS_XP) == 569809640
    total = 0
    for level, xp in enumerate(CATACOMBS_XP):
        assert catacombs_level(total) == level
        assert catacombs_level(total + xp / 2) == level + 0.5
        total += xp
    assert catacombs_level(total) == 50
    assert catacombs_level(total + 200000000) == 51


@pytest.mark.parametrize(
    "extra_xp,expected",
    [
        (-1, 50 - 1 / CATACOMBS_XP[-1]),
        (0, 50),
        (100_000_000, 50.5),
        (199_999_999, 51 - 1 / 200_000_000),
        (200_000_000, 51),
        (200_000_001, 51 + 1 / 200_000_000),
        (650_000_000, 53.25),
    ],
)
def test_card_catacombs_and_all_classes_use_same_overflow(extra_xp, expected):
    data = payload()
    dungeons = data["profiles"][0]["members"][UUID]["dungeons"]
    experience = sum(CATACOMBS_XP) + extra_xp
    dungeons["dungeon_types"]["catacombs"]["experience"] = experience
    roles = ("archer", "berserk", "healer", "mage", "tank")
    dungeons["player_classes"] = {role: {"experience": experience} for role in roles}
    result = parse_profiles(data, UUID)
    assert result["catacombs"]["level"] == pytest.approx(expected)
    assert result["catacombs"]["experience"] == experience
    for role in roles:
        assert result["class_levels"][role] == pytest.approx(expected)


def test_hypixel_hyphenated_profile_id_is_normalized():
    data = payload()
    data["profiles"][0]["profile_id"] = "11111111-1111-1111-1111-111111111111"
    assert parse_profiles(data, UUID)["profile"]["id"] == PROFILE_ID
    data["profiles"][0]["profile_id"] = "11111111111111111111111111111111-"
    with pytest.raises(ValueError):
        parse_profiles(data, UUID)


@pytest.mark.parametrize("value", [None, True, "123", -1, float("nan"), float("inf"), 1e20])
def test_invalid_stats_are_unknown_not_zero(value):
    data = payload()
    member = data["profiles"][0]["members"][UUID]
    member["dungeons"]["secrets"] = value
    member["dungeons"]["dungeon_types"]["catacombs"]["experience"] = value
    member["dungeons"]["player_classes"] = {"mage": {"experience": value}}
    member["accessory_bag_storage"]["highest_magical_power"] = value
    member["dungeons"]["dungeon_types"]["catacombs"]["fastest_time_s_plus"]["7"] = value
    result = parse_profiles(data, UUID)
    assert result["catacombs"] is result["secrets"] is result["magical_power"] is None
    assert result["class_levels"]["mage"] is None
    assert result["floors"][6]["s_plus_ms"] is None


def test_no_profiles_and_missing_optional_data():
    for profiles in (None, []):
        result = parse_profiles({"success": True, "profiles": profiles}, UUID)
        assert result["profile"] is None
        assert result["secrets"] is None
        assert len(result["floors"]) == 14
    data = payload()
    data["profiles"][0]["members"][UUID] = {}
    assert parse_profiles(data, UUID)["magical_power"] is None


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"success": False},
        {"success": True, "profiles": {}},
        {"success": True, "profiles": [{"selected": False}]},
    ],
)
def test_bad_responses_fail_closed(data):
    with pytest.raises(ValueError):
        parse_profiles(data, UUID)


def test_endpoint_is_private_and_uses_session_identity(tmp_path):
    calls = []

    def loader(uuid):
        calls.append(uuid)
        return parse_profiles(payload(), uuid)

    app = create_app(database=tmp_path / "auth.db", card_loader=loader)
    with TestClient(app, base_url="https://mithril.foo") as client:
        assert client.get("/api/v1/auth/player-card").status_code == 401
        assert not calls
        token = app.state.auth.issue("session", UUID, "TestPlayer", 60)
        client.cookies.set(COOKIE, token)
        response = client.get("/api/v1/auth/player-card?uuid=" + "f" * 32)
        assert response.status_code == 200
        assert response.json()["user"] == {"uuid": UUID, "name": "TestPlayer"}
        assert response.headers["cache-control"] == "no-store"
        assert calls == [UUID]
        app.state.auth.revoke(token)
        assert client.get("/api/v1/auth/player-card").status_code == 401


def test_failure_does_not_expose_upstream_details(tmp_path):
    def loader(uuid):
        raise ValueError("synthetic-private-value")

    app = create_app(database=tmp_path / "auth.db", card_loader=loader)
    with TestClient(app, base_url="https://mithril.foo") as client:
        client.cookies.set(COOKIE, app.state.auth.issue("session", UUID, "TestPlayer", 60))
        response = client.get("/api/v1/auth/player-card")
        assert response.status_code == 503
        assert "synthetic-private-value" not in response.text


def test_cache_success_failure_ttl_budget_and_capacity():
    now, calls = [0], []

    def loader(uuid):
        calls.append(uuid)
        if uuid == "bad":
            raise OSError("private")
        return {"profile": None}

    cache = PlayerCardCache(loader, clock=lambda: now[0], wall_clock=lambda: 123)
    assert cache.get(UUID) == {"profile": None, "fetched_at": 123}
    cache.get(UUID)
    assert calls == [UUID]
    now[0] = 300
    cache.get(UUID)
    assert len(calls) == 2
    assert cache.get("bad") is cache.get("bad") is None
    assert calls.count("bad") == 1
    now[0] += 30
    cache.get("bad")
    assert calls.count("bad") == 2
    now[0] += 60
    for index in range(30):
        assert cache.get(str(index)) is not None
    assert cache.get("limited") is None
    now[0] += 301
    assert cache.get("fresh") is not None
    assert list(cache.entries) == ["fresh"]
    cache = PlayerCardCache(loader, clock=lambda: now[0])
    for index in range(150):
        if index % 30 == 0:
            now[0] += 61
        cache.get(str(index))
    assert len(cache.entries) == 128


def test_inflight_requests_are_deduplicated():
    entered, release = Event(), Event()

    def loader(uuid):
        entered.set()
        assert release.wait(5)
        return {}

    cache = PlayerCardCache(loader)
    worker = Thread(target=cache.get, args=(UUID,))
    worker.start()
    try:
        assert entered.wait(5)
        assert cache.get(UUID) is None
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()


@pytest.mark.parametrize(
    "status,encoding,body",
    [
        (403, "identity", b"secret"),
        (429, "identity", b"limited"),
        (302, "identity", b""),
        (200, "gzip", b"bad"),
        (200, "identity", b"{"),
        (200, "identity", b"x" * (MAX_RESPONSE + 1)),
    ],
    ids=["invalid-key", "throttled", "redirect", "compressed", "invalid-json", "oversized"],
)
def test_transport_bounds_redirects_errors_and_closes(monkeypatch, status, encoding, body):
    monkeypatch.setenv("HYPIXEL_API_KEY", "synthetic-test-key")

    class Connection:
        closed = False

        def __init__(self, host, timeout):
            assert host == "api.hypixel.net"
            assert timeout == 4

        def request(self, method, path, headers):
            assert method == "GET"
            assert path == f"/v2/skyblock/profiles?uuid={UUID}"
            assert headers["API-Key"] == "synthetic-test-key"
            assert "synthetic-test-key" not in path

        def getresponse(self):
            self.status = status
            return self

        def getheader(self, name, default):
            return encoding

        def read(self, limit):
            assert limit == MAX_RESPONSE + 1
            return body

        def close(self):
            Connection.closed = True

    with pytest.raises(ValueError):
        fetch_card(UUID, connection_factory=Connection)
    assert Connection.closed


def test_missing_key_never_connects(monkeypatch):
    monkeypatch.delenv("HYPIXEL_API_KEY", raising=False)
    with pytest.raises(ValueError):
        fetch_card(UUID, connection_factory=lambda *args, **kwargs: pytest.fail("network"))
