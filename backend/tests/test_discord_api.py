import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.discord_api import create_internal, summary
from mithril_web.parties import Finder
from mithril_web.party_api import StatsService
from mithril_web.releases import ReleaseCache, discord_release
from mithril_web.serve import Listeners, main

SECRET = "a" * 64
HEADERS = {"Authorization": f"Bearer {SECRET}"}
PUBLIC = "https://github.com/MithrilAddons/mithrilpf/releases"
RELEASE = {
    "tag_name": "v1.2.3",
    "draft": False,
    "prerelease": False,
    "body": "Synthetic notes",
    "assets": [
        {
            "name": "mithrilpf-1.2.3.jar",
            "state": "uploaded",
            "browser_download_url": f"{PUBLIC}/download/v1.2.3/mithrilpf-1.2.3.jar",
            "digest": "sha256:" + "b" * 64,
        }
    ],
}


@pytest.fixture
def public(tmp_path):
    return create_app(database=tmp_path / "auth.sqlite3", release_loader=lambda: None)


def test_separate_routes_and_constant_secret(public):
    internal = create_internal(public, SECRET)
    with TestClient(public, base_url="http://localhost") as client:
        assert client.get("/internal/v1/summary", headers=HEADERS).status_code == 404
        assert client.get("/internal/v1/releases", headers=HEADERS).status_code == 404
        with TestClient(internal, client=("127.0.0.1", 100)) as bot:
            assert bot.get("/internal/v1/summary").status_code == 401
            assert (
                bot.get(
                    "/internal/v1/summary", headers={"Authorization": "Bearer wrong"}
                ).status_code
                == 401
            )
            response = bot.get("/internal/v1/summary", headers=HEADERS)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.json()["hypixel"] == "unknown"
            assert bot.get("/api/v1/health", headers=HEADERS).status_code == 404
            assert bot.post("/internal/v1/summary", headers=HEADERS).status_code == 405
            assert bot.get("/internal/v1/releases", headers=HEADERS).json()["version"] == 1
            assert (
                bot.get(
                    "/internal/v1/summary", headers={**HEADERS, "Content-Length": "1"}
                ).status_code
                == 405
            )
            assert (
                bot.get(
                    "/internal/v1/summary", headers={**HEADERS, "Transfer-Encoding": "chunked"}
                ).status_code
                == 400
            )
    with TestClient(internal, client=("203.0.113.1", 100)) as untrusted:
        assert (
            untrusted.get(
                "/internal/v1/summary", headers={**HEADERS, "X-Forwarded-For": "127.0.0.1"}
            ).status_code
            == 401
        )
    for secret in ("", "short", "g" * 64):
        with pytest.raises(ValueError):
            create_internal(public, secret)


def test_counts_exclude_full_paused_completed_parties_and_names():
    finder = Finder(lambda: 1000)

    def party():
        return SimpleNamespace(
            floor="M7", paused=False, completed=False, open_roles=lambda: ["mage"]
        )

    open_party = party()
    paused = party()
    paused.paused = True
    completed = party()
    completed.completed = True
    full = party()
    full.open_roles = lambda: []
    finder.parties = dict(enumerate((open_party, paused, completed, full)))
    finder.players = {
        "private-uuid": SimpleNamespace(looking={"floor": "F7"}),
        "other": SimpleNamespace(looking=None),
    }
    stats = StatsService(lambda _: None, lambda _: [], clock=lambda: 1000)
    value = summary(finder, stats, {})
    assert value["floors"] == {
        "F7": {"open_parties": 0, "looking": 1},
        "M7": {"open_parties": 1, "looking": 0},
    }
    assert "private-uuid" not in json.dumps(value)
    for outcomes, expected in [
        ([(999, True, 1)], "ok"),
        ([(999, True, 3)], "slow"),
        ([(999, False, 1)], "failing"),
        ([(1, False, 1)], "unknown"),
    ]:
        stats.outcomes.clear()
        stats.outcomes.extend(outcomes)
        assert summary(finder, stats, {})["hypixel"] == expected


def test_hypixel_health_uses_existing_outcomes_without_extra_fetches():
    loader = Mock(side_effect=[{"floors": []}, ValueError("unavailable")])
    stats = StatsService(loader, lambda _: [], clock=lambda: 1000)
    asyncio.run(stats._fetch("a" * 32, 1000))
    asyncio.run(stats._fetch("b" * 32, 1000))
    assert [item[1] for item in stats.outcomes] == [True, False]
    summary(Finder(lambda: 1000), stats, {})
    assert loader.call_count == 2


def test_public_and_bot_share_one_release_fetch(monkeypatch):
    loader = Mock(return_value=[RELEASE])
    monkeypatch.setattr("mithril_web.releases.fetch_release_catalog", loader)
    cache = ReleaseCache(clock=lambda: 100)
    assert cache.get()["release"]["version"] == "1.2.3"
    assert cache.discord()["releases"] == [discord_release(RELEASE)]
    loader.assert_called_once()
    assert "sha256" not in cache.get()["release"]


def test_missing_digest_drafts_and_bad_notes_not_announced(monkeypatch):
    bad = copy.deepcopy(RELEASE)
    bad["assets"][0].pop("digest")
    loader = Mock(return_value=[bad, {**RELEASE, "draft": True}, {**RELEASE, "body": 7}])
    monkeypatch.setattr("mithril_web.releases.fetch_release_catalog", loader)
    cache = ReleaseCache()
    assert cache.discord()["releases"] == []
    assert cache.get()["status"] == "ready"


def test_release_staleness_order_and_no_redirects(monkeypatch):
    newer = copy.deepcopy(RELEASE)
    newer["tag_name"] = "v2.0.0-rc.1"
    newer["prerelease"] = True
    newer["assets"][0]["name"] = "mithrilpf-2.0.0-rc.1.jar"
    newer["assets"][0]["browser_download_url"] = (
        f"{PUBLIC}/download/v2.0.0-rc.1/mithrilpf-2.0.0-rc.1.jar"
    )
    loader = Mock(side_effect=[[RELEASE, newer], OSError("offline")])
    monkeypatch.setattr("mithril_web.releases.fetch_release_catalog", loader)
    now = [0]
    cache = ReleaseCache(clock=lambda: now[0])
    assert cache.discord()["releases"][0]["version"] == "2.0.0-rc.1"
    now[0] = 301
    assert cache.discord()["status"] == "stale"
    assert len(cache.discord()["releases"]) == 2


def test_listener_dispatch_uses_socket_port_not_headers():
    async def check():
        public, internal = AsyncMock(), AsyncMock()
        app = Listeners(public, internal)
        receive, send = AsyncMock(), AsyncMock()
        await app({"type": "lifespan"}, receive, send)
        public.assert_awaited_once()
        scope = {
            "type": "http",
            "server": ("127.0.0.1", 8781),
            "client": ("127.0.0.1", 1),
            "headers": [(b"x-forwarded-for", b"198.51.100.1")],
        }
        await app(scope, receive, send)
        assert internal.call_args.args[0]["client"][0] == "127.0.0.1"
        scope["server"] = ("127.0.0.1", 8780)
        await app(scope, receive, send)
        assert public.call_args.args[0]["client"][0] == "198.51.100.1"

    asyncio.run(check())


def test_server_binds_only_loopback_and_one_process(monkeypatch, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text(SECRET)
    monkeypatch.setenv("MITHRIL_DISCORD_SECRET_FILE", str(secret))
    sockets = [Mock(), Mock()]
    for sock in sockets:
        sock.__enter__ = Mock(return_value=sock)
        sock.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("mithril_web.serve.socket.socket", Mock(side_effect=sockets))
    server = Mock()
    monkeypatch.setattr("mithril_web.serve.uvicorn.Server", Mock(return_value=server))
    main()
    sockets[0].bind.assert_called_once_with(("127.0.0.1", 8780))
    sockets[1].bind.assert_called_once_with(("127.0.0.1", 8781))
    server.run.assert_called_once_with(sockets=sockets)


def test_foundation_contract_fixture(public):
    fixture = json.loads(
        (Path(__file__).parents[2] / "contracts" / "discord-foundation-v1.json").read_text()
    )
    assert fixture["summary"]["version"] == 1
    assert set(fixture["summary"]["floors"]) == {"F7", "M7"}
    assert discord_release(RELEASE) == fixture["releases"]["releases"][0]
    internal = create_internal(public, SECRET)
    with TestClient(internal, client=("127.0.0.1", 1)) as client:
        actual = client.get("/internal/v1/summary", headers=HEADERS).json()
        assert actual.keys() == fixture["summary"].keys()
