import base64
import hashlib
import io
import json
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient
from mithril_web import curator_icons
from mithril_web.app import create_app
from mithril_web.curator_icons import flat_texture, head_icon, pack_location, pack_textures
from PIL import Image

NOW = 1_800_000_000.0
SKIN = "/texture/" + "ab" * 32


def png(size, colour=(200, 40, 40, 255)):
    output = io.BytesIO()
    Image.new("RGBA", size, colour).save(output, "PNG")
    return output.getvalue()


def skin_value(url=f"http://textures.minecraft.net{SKIN}"):
    return base64.b64encode(json.dumps({"textures": {"SKIN": {"url": url}}}).encode()).decode()


def skin_image():
    """A synthetic 64×64 skin: a blue face with a red hat pixel in the hat layer's corner."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    image.paste((30, 60, 200, 255), (8, 8, 16, 16))
    image.putpixel((40, 8), (255, 0, 0, 255))
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def pack():
    files = {
        "LICENSE": b"Synthetic",
        "assets/hypixel_skyblock/items/item/swords/hyperion.json": {
            "model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/swords/hyperion"}
        },
        "assets/hypixel_skyblock/models/item/swords/hyperion.json": {
            "textures": {"layer0": "hypixel_skyblock:item/swords/hyperion"}
        },
        "assets/hypixel_skyblock/textures/item/swords/hyperion.png": png((16, 16)),
        # An animated strip keeps only its first frame.
        "assets/hypixel_skyblock/items/item/glowing.json": {
            "model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/glowing"}
        },
        "assets/hypixel_skyblock/models/item/glowing.json": {
            "textures": {"layer0": "hypixel_skyblock:item/glowing"}
        },
        "assets/hypixel_skyblock/textures/item/glowing.png": png((16, 48)),
        # Dispatching definitions, escapes and missing files are skipped.
        "assets/hypixel_skyblock/items/item/select.json": {"model": {"type": "minecraft:select"}},
        "assets/hypixel_skyblock/items/item/escape.json": {
            "model": {"type": "minecraft:model", "model": "hypixel_skyblock:../secret"}
        },
        "assets/hypixel_skyblock/items/item/missing.json": {
            "model": {"type": "minecraft:model", "model": "hypixel_skyblock:item/missing"}
        },
        "assets/hypixel_skyblock/items/item/text.json": {"model": "not an object"},
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content if isinstance(content, bytes) else json.dumps(content))
    return output.getvalue()


def listing(archive, deploy="deploy-1"):
    digest = hashlib.sha1(archive, usedforsecurity=False).hexdigest()
    return {
        "packs": [
            {"id": "Other", "versions": []},
            {
                "id": "SkyBlock",
                "deployId": deploy,
                "versions": [
                    {"packFormat": 84, "hash": "0" * 40, "url": "https://example.com/old.zip"},
                    {
                        "packFormat": 97,
                        "hash": digest,
                        "url": f"https://resourcepacks.hypixel.net/SkyBlock/{deploy}/97.zip",
                    },
                ],
            },
        ]
    }


def test_pack_textures_take_flat_item_models_and_skip_the_rest():
    textures = pack_textures(pack())
    assert set(textures) == {"HYPERION", "GLOWING"}
    with Image.open(io.BytesIO(textures["GLOWING"])) as image:
        assert image.size == (16, 16)
    for size in ((16, 20), (4, 4)):
        texture = png(size)
        with pytest.raises(ValueError):
            flat_texture(texture)


def test_pack_location_uses_the_newest_format_on_hypixels_host():
    archive = pack()
    path, digest = pack_location(listing(archive)["packs"][1])
    assert path == "/SkyBlock/deploy-1/97.zip"
    assert digest == hashlib.sha1(archive, usedforsecurity=False).hexdigest()
    for url in ("https://example.com/97.zip", "https://resourcepacks.hypixel.net/../x.zip"):
        with pytest.raises(ValueError):
            pack_location({"versions": [{"packFormat": 1, "hash": "0" * 40, "url": url}]})


def test_heads_use_the_face_and_hat_from_mojangs_texture_server():
    assert curator_icons.skin_path(skin_value()) == SKIN
    for bad in (
        skin_value("https://example.com/texture/abc"),
        "not base64!",
        base64.b64encode(b"\xff").decode(),
        None,
    ):
        with pytest.raises((ValueError, KeyError, TypeError)):
            curator_icons.skin_path(bad)
    with Image.open(io.BytesIO(head_icon(skin_image()))) as face:
        assert face.size == (16, 16)
        assert face.getpixel((0, 0)) == (255, 0, 0, 255)
        assert face.getpixel((8, 8)) == (30, 60, 200, 255)
    square = png((32, 32))
    with pytest.raises(ValueError):
        head_icon(square)


def items():
    fillers = [{"id": f"FILLER_{n:04}", "name": f"Filler {n}", "tier": "RARE"} for n in range(1000)]
    return {
        "lastUpdated": 1,
        "items": [
            *fillers,
            {"id": "HYPERION", "name": "Hyperion", "tier": "LEGENDARY", "material": "IRON_SWORD"},
            {
                "id": "WITHER_GOGGLES",
                "name": "Wither Goggles",
                "tier": "EPIC",
                "material": "SKULL_ITEM",
                "skin": {"value": skin_value()},
            },
            {
                "id": "BROKEN_HEAD",
                "name": "Broken Head",
                "tier": "EPIC",
                "material": "SKULL_ITEM",
                "skin": {"value": skin_value("https://example.com/x")},
            },
        ],
    }


@pytest.fixture
def icons(tmp_path):
    archive = pack()
    sources = {"resources/skyblock/items": items(), "resources/packs": listing(archive)}
    downloads = []
    files = {curator_icons.PACK_HOST: archive, curator_icons.SKIN_HOST: skin_image()}

    def loader(path):
        if threading.current_thread().name.startswith("asyncio"):
            raise ValueError("Background refresh disabled in this test")
        return sources[path]

    def download(host, path, limit):
        downloads.append((host, path, limit))
        if isinstance(files[host], Exception):
            raise files[host]
        return files[host]

    app = create_app(database=tmp_path / "auth.db", clock=lambda: NOW, curator_loader=loader)
    with TestClient(app, base_url="https://mithril.foo") as client:
        app.state.curator.download = download
        app.state.curator.load_catalog()
        yield client, app, sources, downloads, files


def test_icons_come_from_the_pack_and_heads_and_are_cached(icons):
    client, app, sources, downloads, files = icons
    data = app.state.curator
    data.load_icons()
    data.load_icons()
    assert [host for host, _, _ in downloads] == [curator_icons.PACK_HOST]
    response = client.get("/api/v1/games/curator/icon/HYPERION.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    head = client.get("/api/v1/games/curator/icon/WITHER_GOGGLES.png")
    assert head.status_code == 200
    assert client.get("/api/v1/games/curator/icon/WITHER_GOGGLES.png").content == head.content
    assert [host for host, _, _ in downloads].count(curator_icons.SKIN_HOST) == 1
    for missing in ("FILLER_0001", "BROKEN_HEAD", "UNKNOWN", "bad%20id"):
        response = client.get(f"/api/v1/games/curator/icon/{missing}.png")
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
    # A new deploy is downloaded again; a failed check leaves the old icons in place.
    sources["resources/packs"] = listing(pack(), "deploy-2")
    files[curator_icons.PACK_HOST] = b"truncated"
    with pytest.raises(ValueError):
        data.load_icons()
    assert client.get("/api/v1/games/curator/icon/HYPERION.png").status_code == 200


def test_a_head_that_cant_be_fetched_is_tried_again_later(icons):
    client, app, _, downloads, files = icons
    files[curator_icons.SKIN_HOST] = OSError("offline")
    response = client.get("/api/v1/games/curator/icon/WITHER_GOGGLES.png")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    files[curator_icons.SKIN_HOST] = skin_image()
    assert client.get("/api/v1/games/curator/icon/WITHER_GOGGLES.png").status_code == 200
    data = app.state.curator
    for _ in range(2):
        data.head_slots.acquire()
    data.db.execute("DELETE FROM curator_icons")
    assert data.icon("WITHER_GOGGLES") is False


def test_pack_refresh_failures_are_retried(icons):
    _, app, sources, _, files = icons
    data = app.state.curator
    sources["resources/packs"] = {"packs": [{"id": "Other"}]}
    with pytest.raises(ValueError):
        data.load_icons()
    empty = b"PK\x05\x06" + b"\x00" * 18
    sources["resources/packs"] = listing(empty)
    files[curator_icons.PACK_HOST] = empty
    with pytest.raises(ValueError):
        data.load_icons()
    files[curator_icons.PACK_HOST] = b"not a zip"
    sources["resources/packs"] = listing(b"not a zip")
    data.refresh()
    assert data.next["icons"] == NOW + 60
