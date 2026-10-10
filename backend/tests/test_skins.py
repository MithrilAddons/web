import base64
import json
import struct

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE
from mithril_web.parties import CLASSES, player_stats
from mithril_web.skins import SkinCache, fetch_skin, get_bytes, texture_details

UUID = "0123456789abcdef0123456789abcdef"
URL = "http://textures.minecraft.net/texture/" + "a" * 64


def profile(url=URL, model="slim"):
    value = {"textures": {"SKIN": {"url": url, "metadata": {"model": model}}}}
    return {
        "id": UUID,
        "properties": [
            {"name": "textures", "value": base64.b64encode(json.dumps(value).encode()).decode()}
        ],
    }


def png_header(width=64, height=64):
    return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", width, height) + bytes(9)


@pytest.mark.parametrize("model", ["slim", "default"])
def test_fixed_destinations_and_model(model):
    calls = []

    def fetch(host, path, limit):
        calls.append((host, path, limit))
        return json.dumps(profile(model=model)).encode() if len(calls) == 1 else png_header()

    result = fetch_skin(UUID, fetch)
    assert result["model"] == model
    assert result["image"].startswith("data:image/png;base64,")
    assert calls == [
        ("sessionserver.mojang.com", f"/session/minecraft/profile/{UUID}", 32768),
        ("textures.minecraft.net", "/texture/" + "a" * 64, 65536),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.invalid/texture/" + "a" * 64,
        "http://127.0.0.1/private",
        URL + "?x=1",
        URL + "#fragment",
        URL.replace(".net/", ".net.evil/"),
        "https://textures.minecraft.net@evil.invalid/texture/" + "a" * 64,
    ],
)
def test_rejects_untrusted_texture_urls(url):
    untrusted = profile(url=url)
    with pytest.raises(ValueError):
        texture_details(untrusted, UUID)


@pytest.mark.parametrize(
    "data",
    [b"bad", png_header(8192), png_header(height=128), png_header() + bytes(65536)],
    ids=["bad-signature", "too-wide", "too-tall", "oversized"],
)
def test_rejects_invalid_or_large_images(data):
    with pytest.raises(ValueError):
        fetch_skin(
            UUID,
            lambda host, path, limit: (
                json.dumps(profile()).encode() if host == "sessionserver.mojang.com" else data
            ),
        )


def test_wrong_profile_and_missing_skin():
    valid = profile()
    with pytest.raises(ValueError):
        texture_details(valid, "f" * 32)
    with pytest.raises(ValueError):
        texture_details({"id": UUID}, UUID)


def test_cache_ttl_failure_and_capacity():
    now = [0]
    calls = []

    def loader(uuid):
        calls.append(uuid)
        if uuid == "bad":
            raise OSError("private")
        return {"model": "default"}

    cache = SkinCache(loader, clock=lambda: now[0])
    assert cache.get(UUID) == cache.get(UUID)
    assert len(calls) == 1
    now[0] = 300
    cache.get(UUID)
    assert len(calls) == 2
    assert cache.get("bad") is None
    assert cache.get("bad") is None
    assert calls.count("bad") == 1
    for number in range(130):
        cache.get(str(number))
    assert len(cache.entries) == 128


def test_endpoint_uses_session_uuid_not_query(tmp_path):
    calls = []

    def loader(uuid):
        calls.append(uuid)
        return {"image": "data:image/png;base64,AAAA", "model": "slim"}

    app = create_app(database=tmp_path / "auth.db", skin_loader=loader)
    with TestClient(app, base_url="https://mithril.foo") as client:
        assert client.get("/api/v1/auth/skin").status_code == 401
        assert calls == []
        token = app.state.auth.issue("session", UUID, "TestPlayer", 60)
        client.cookies.set(COOKIE, token)
        result = client.get("/api/v1/auth/skin?uuid=" + "f" * 32)
        assert result.status_code == 200
        assert calls == [UUID]
        assert result.headers["cache-control"] == "no-store"
        assert "set-cookie" not in result.headers
        app.state.auth.revoke(token)
        assert client.get("/api/v1/auth/skin").status_code == 401


def test_upstream_limits_close_connections_and_do_not_follow_redirects(monkeypatch):
    class Connection:
        closed = False
        status = 200
        limit = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return self

        def getheader(self, name, default):
            return default

        def read(self, limit):
            Connection.limit = limit
            return bytes(limit)

        def close(self):
            Connection.closed = True

    monkeypatch.setattr("mithril_web.skins.http.client.HTTPSConnection", Connection)
    with pytest.raises(ValueError):
        get_bytes("textures.minecraft.net", "/texture/a", 10)
    assert Connection.closed
    assert Connection.limit == 11
    Connection.closed = False
    Connection.limit = None
    Connection.status = 302
    with pytest.raises(ValueError):
        get_bytes("textures.minecraft.net", "/texture/a", 10)
    assert Connection.closed
    assert Connection.limit is None


def test_party_skins_require_membership_reuse_cache_and_allow_retained_senders(tmp_path):
    calls = []

    def loader(uuid):
        calls.append(uuid)
        return {"image": "data:image/png;base64,AAAA", "model": "default"}

    app = create_app(database=tmp_path / "auth.db", skin_loader=loader)
    other = "a" * 32
    with TestClient(app, base_url="https://mithril.foo") as client:
        path = f"/api/v1/party/skin/{other}"
        assert client.get(path).status_code == 401
        token = app.state.auth.issue("session", UUID, "TestPlayer", 60)
        client.cookies.set(COOKIE, token)
        assert client.get(path).status_code == 404
        assert client.get("/api/v1/party/skin/not-a-uuid").status_code == 404
        assert calls == []
        assert client.get("/api/v1/auth/skin").status_code == 200
        assert client.get(f"/api/v1/party/skin/{UUID}").status_code == 200
        assert calls == [UUID]
        finder = app.state.finder
        for uuid, name in [(UUID, "TestPlayer"), (other, "PartyPlayer")]:
            finder.seen(uuid, name, "web")
            finder.set_stats(uuid, player_stats({}, []))
        party = finder.publish(UUID, "M7", "archer", list(CLASSES), False, {}, {})
        finder.reserve(other, party, "mage")
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert calls == [UUID, other]
        finder.send_chat(other, party, "a" * 16, "hello", "web")
        finder.leave(other)
        assert client.get(path).status_code == 200
        assert calls == [UUID, other]
        finder.leave(UUID)
        assert client.get(path).status_code == 404
        app.state.auth.revoke(token)
        assert client.get(f"/api/v1/party/skin/{UUID}").status_code == 401


def test_party_skin_failure_is_graceful(tmp_path):
    app = create_app(database=tmp_path / "auth.db", skin_loader=lambda _: None)
    with TestClient(app, base_url="https://mithril.foo") as client:
        token = app.state.auth.issue("session", UUID, "TestPlayer", 60)
        client.cookies.set(COOKIE, token)
        assert client.get(f"/api/v1/party/skin/{UUID}").status_code == 503
