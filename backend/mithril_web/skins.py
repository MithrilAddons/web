"""Bounded Mojang skin fetches; never accept a destination URL from a browser."""

import base64
import http.client
import json
import re
import struct
import threading
import time
from collections import OrderedDict


def get_bytes(host, path, limit):
    connection = http.client.HTTPSConnection(host, timeout=4)
    try:
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("Skin unavailable")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Skin response too large")
        return data
    finally:
        connection.close()


def texture_details(profile, uuid):
    if not isinstance(profile, dict) or profile.get("id") != uuid:
        raise ValueError("Wrong profile")
    properties = profile.get("properties", [])
    if not isinstance(properties, list):
        raise ValueError("Invalid properties")
    prop = next(
        (p for p in properties if isinstance(p, dict) and p.get("name") == "textures"), None
    )
    if not prop or not isinstance(prop.get("value"), str) or len(prop["value"]) > 16384:
        raise ValueError("No skin")
    textures = json.loads(base64.b64decode(prop["value"], validate=True))
    skin = textures["textures"]["SKIN"]
    # Old Mojang profiles use HTTP URLs: validate that exact host/path, then fetch HTTPS.
    url = skin["url"]
    if not isinstance(url, str):
        raise ValueError("Invalid texture URL")
    match = re.fullmatch(r"https?://textures\.minecraft\.net(/texture/[0-9a-f]{32,64})", url)
    if not match:
        raise ValueError("Untrusted texture URL")
    model = skin.get("metadata", {}).get("model", "default")
    if model not in ("default", "slim"):
        raise ValueError("Invalid model")
    return match[1], model


def fetch_skin(uuid, fetch=get_bytes):
    if not re.fullmatch(r"[0-9a-f]{32}", uuid):
        raise ValueError("Invalid UUID")
    profile = json.loads(
        fetch("sessionserver.mojang.com", f"/session/minecraft/profile/{uuid}", 32768)
    )
    path, model = texture_details(profile, uuid)
    image = fetch("textures.minecraft.net", path, 65536)
    if (
        len(image) < 33
        or len(image) > 65536
        or image[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        or struct.unpack(">II", image[16:24]) not in ((64, 64), (64, 32))
    ):
        raise ValueError("Invalid skin image")
    return {"image": "data:image/png;base64," + base64.b64encode(image).decode(), "model": model}


class SkinCache:
    """Five-minute, 128-account memory cache; at most two network fetches at once."""

    def __init__(self, loader=fetch_skin, clock=time.monotonic):
        self.loader = loader
        self.clock = clock
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.entries = OrderedDict()
        self.pending = set()
        self.erased_pending = set()

    def get(self, uuid):
        with self.lock:
            if uuid in self.entries:
                expires, value = self.entries[uuid]
                if expires > self.clock():
                    self.entries.move_to_end(uuid)
                    return value
                del self.entries[uuid]
            if uuid in self.pending or not self.slots.acquire(blocking=False):
                return None
            self.pending.add(uuid)
        value = None
        try:
            value = self.loader(uuid)
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            http.client.HTTPException,
        ):
            pass
        finally:
            with self.lock:
                if uuid in self.erased_pending:
                    self.erased_pending.remove(uuid)
                    value = None
                else:
                    self.entries[uuid] = (self.clock() + (300 if value else 30), value)
                while len(self.entries) > 128:
                    self.entries.popitem(last=False)
                self.pending.remove(uuid)
            self.slots.release()
        return value

    def erase(self, uuid):
        with self.lock:
            self.entries.pop(uuid, None)
            if uuid in self.pending:
                self.erased_pending.add(uuid)
