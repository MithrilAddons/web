"""Item icons for Curator on the website.

Icons come from Hypixel's SkyBlock Resource Pack and from custom head skins on Mojang's texture
server. The pack's license lets Hypixel-related websites use its assets free of charge, provided
they are not sold or charged for, credited to Hypixel and not presented as endorsed by it; head
skins are treated the same way. The files are fetched at runtime and never stored in this
repository, so they stay under Hypixel's license rather than this project's.
"""

import base64
import binascii
import io
import json
import re
import zipfile

from PIL import Image, UnidentifiedImageError

PACK_HOST = "resourcepacks.hypixel.net"
MAX_PACK = 64 * 1024 * 1024
MAX_FILE = 256 * 1024
SKIN_HOST = "textures.minecraft.net"
ITEM_DEFINITION = re.compile(r"assets/hypixel_skyblock/items/(?:[a-z0-9_./-]+/)?([a-z0-9_]+)\.json")
RESOURCE = re.compile(r"(?:([a-z0-9_.-]+):)?([a-z0-9_/.-]+)")
FAILURES = (
    KeyError,
    TypeError,
    ValueError,
    OSError,
    zipfile.BadZipFile,
    UnidentifiedImageError,
    Image.DecompressionBombError,
)


def pack_location(pack):
    """The download path and SHA-1 of the newest format of Hypixel's SkyBlock pack."""
    version = max(pack["versions"], key=lambda entry: entry["packFormat"])
    match = re.fullmatch(
        r"https://resourcepacks\.hypixel\.net(/[A-Za-z0-9_./-]+\.zip)", version["url"]
    )
    digest = version["hash"]
    if not match or ".." in match[1] or not re.fullmatch(r"[0-9a-f]{40}", digest):
        raise ValueError("Unexpected pack location")
    return match[1], digest


def _path(reference, kind, suffix):
    match = RESOURCE.fullmatch(reference) if isinstance(reference, str) else None
    if not match or ".." in match[2]:
        raise ValueError("Unexpected resource name")
    return f"assets/{match[1] or 'minecraft'}/{kind}/{match[2]}{suffix}"


def _png(image):
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()


def flat_texture(data):
    """A pack texture as a square PNG: the first frame of an animated strip, metadata dropped."""
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if not 8 <= width <= 128 or height % width or height // width > 64:
            raise ValueError("Unexpected texture size")
        return _png(image.convert("RGBA").crop((0, 0, width, width)))


def pack_textures(archive):
    """Item ID to icon PNG for every item the pack draws as one flat texture."""
    textures = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as pack:

        def read(name):
            if pack.getinfo(name).file_size > MAX_FILE:
                raise ValueError("Pack file too large")
            return pack.read(name)

        for name in sorted(pack.namelist()):
            definition = ITEM_DEFINITION.fullmatch(name)
            if not definition:
                continue
            try:
                model = json.loads(read(name))["model"]
                if model.get("type") != "minecraft:model":
                    continue
                layers = json.loads(read(_path(model["model"], "models", ".json")))["textures"]
                icon = flat_texture(read(_path(layers["layer0"], "textures", ".png")))
            except (*FAILURES, AttributeError):
                continue
            textures[definition[1].upper()] = icon
    return textures


def skin_path(value):
    """The texture server path of a head's skin, from its base64 textures value."""
    if not isinstance(value, str) or len(value) > 16384:
        raise ValueError("Invalid skin")
    try:
        url = json.loads(base64.b64decode(value, validate=True))["textures"]["SKIN"]["url"]
    except (binascii.Error, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Invalid skin") from error
    match = re.fullmatch(r"https?://textures\.minecraft\.net(/texture/[0-9a-f]{32,64})", url)
    if not match:
        raise ValueError("Untrusted texture URL")
    return match[1]


def head_icon(data):
    """A head's face and hat layer, drawn at the pack's 16×16 icon size."""
    with Image.open(io.BytesIO(data)) as skin:
        if skin.format != "PNG" or skin.size not in ((64, 64), (64, 32)):
            raise ValueError("Invalid skin image")
        skin = skin.convert("RGBA")
        face = skin.crop((8, 8, 16, 16))
        face.alpha_composite(skin.crop((40, 8, 48, 16)))
        return _png(face.resize((16, 16), Image.Resampling.NEAREST))
