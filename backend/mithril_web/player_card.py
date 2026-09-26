"""Read-only selected-profile summary. The Hypixel key never leaves this backend."""

import http.client
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque

# Factual level requirements, cross-checked against NEU's constants/leveling.json.
# https://github.com/NotEnoughUpdates/NotEnoughUpdates-REPO/blob/master/constants/leveling.json
CATACOMBS_XP = (
    50,
    75,
    110,
    160,
    230,
    330,
    470,
    670,
    950,
    1340,
    1890,
    2665,
    3760,
    5260,
    7380,
    10300,
    14400,
    20000,
    27600,
    38000,
    52500,
    71500,
    97000,
    132000,
    180000,
    243000,
    328000,
    445000,
    600000,
    800000,
    1065000,
    1410000,
    1900000,
    2500000,
    3300000,
    4300000,
    5600000,
    7200000,
    9200000,
    12000000,
    15000000,
    19000000,
    24000000,
    30000000,
    38000000,
    48000000,
    60000000,
    75000000,
    93000000,
    116250000,
)
MAX_RESPONSE = 16 * 1024 * 1024


def number(value, maximum=1e15):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        return None
    return value


def catacombs_level(experience):
    if number(experience) is None:
        return None
    remaining = experience
    for level, required in enumerate(CATACOMBS_XP):
        if remaining < required:
            return level + remaining / required
        remaining -= required
    return 50.0 + remaining / 200_000_000


def object_value(value):
    return value if isinstance(value, dict) else {}


def parse_profiles(payload, uuid):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Profiles unavailable")
    profiles = payload.get("profiles")
    if profiles is None:
        profiles = []
    if not isinstance(profiles, list) or len(profiles) > 32:
        raise ValueError("Invalid profile list")
    selected = [p for p in profiles if isinstance(p, dict) and p.get("selected") is True]
    if len(selected) > 1 or (profiles and not selected):
        raise ValueError("Selected profile unavailable")
    profile = selected[0] if selected else None
    member = object_value(object_value(profile).get("members")).get(uuid)
    if profile is not None and not isinstance(member, dict):
        raise ValueError("Selected member unavailable")
    member = object_value(member)
    dungeons = object_value(member.get("dungeons"))
    types = object_value(dungeons.get("dungeon_types"))
    xp = number(object_value(types.get("catacombs")).get("experience"))
    result = {
        "profile": None,
        "catacombs": {"level": catacombs_level(xp), "experience": xp} if xp is not None else None,
        "secrets": number(dungeons.get("secrets")),
        "magical_power": number(
            object_value(member.get("accessory_bag_storage")).get("highest_magical_power")
        ),
        "magical_power_basis": "highest_recorded",
        # Dungeon classes level on the same XP curve as Catacombs.
        "class_levels": {
            role: catacombs_level(
                number(
                    object_value(object_value(dungeons.get("player_classes")).get(role)).get(
                        "experience"
                    )
                )
            )
            for role in ("archer", "berserk", "healer", "mage", "tank")
        },
        "mod_records_available": False,
        "floors": [],
    }
    if profile is not None:
        name, profile_id = profile.get("cute_name"), profile.get("profile_id")
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ValueError("Invalid profile name")
        if not isinstance(profile_id, str) or not re.fullmatch(
            r"(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})", profile_id
        ):
            raise ValueError("Invalid profile ID")
        result["profile"] = {"id": profile_id.replace("-", ""), "name": name}
    for prefix, kind in (("F", "catacombs"), ("M", "master_catacombs")):
        data = object_value(types.get(kind))
        for floor in range(1, 8):
            value = number(object_value(data.get("fastest_time_s_plus")).get(str(floor)), 604800000)
            result["floors"].append(
                {
                    "floor": f"{prefix}{floor}",
                    "s_plus_ms": value if value is not None and value > 0 else None,
                    "solo_clear_ms": None,
                    "ss_ms": None,
                    "terminals_ms": None,
                }
            )
    return result


def fetch_card(uuid, *, connection_factory=http.client.HTTPSConnection):
    if not re.fullmatch(r"[0-9a-f]{32}", uuid):
        raise ValueError("Invalid UUID")
    key = os.environ.get("HYPIXEL_API_KEY", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", key):
        raise ValueError("Hypixel unavailable")
    connection = connection_factory("api.hypixel.net", timeout=4)
    try:
        connection.request(
            "GET",
            f"/v2/skyblock/profiles?uuid={uuid}",
            headers={
                "API-Key": key,
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("Hypixel unavailable")
        data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Profiles response too large")
        return parse_profiles(json.loads(data), uuid)
    finally:
        connection.close()


class PlayerCardCache:
    """Cache summaries only: 5 minutes/128 accounts, 2 fetches, at most 30 attempts/minute."""

    def __init__(self, loader=fetch_card, clock=time.monotonic, wall_clock=time.time):
        self.loader, self.clock, self.wall_clock = loader, clock, wall_clock
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.pending = set()
        self.attempts = deque()

    def get(self, uuid):
        with self.lock:
            now = self.clock()
            for expired in [key for key, (expiry, _) in self.entries.items() if expiry <= now]:
                del self.entries[expired]
            cached = self.entries.get(uuid)
            if cached and cached[0] > now:
                self.entries.move_to_end(uuid)
                return cached[1]
            while self.attempts and self.attempts[0] <= now - 60:
                self.attempts.popleft()
            if uuid in self.pending or len(self.pending) >= 2 or len(self.attempts) >= 30:
                return None
            self.pending.add(uuid)
            self.attempts.append(now)
        value = None
        try:
            value = {**self.loader(uuid), "fetched_at": int(self.wall_clock())}
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            pass
        finally:
            with self.lock:
                self.entries[uuid] = (self.clock() + (300 if value else 30), value)
                self.entries.move_to_end(uuid)
                while len(self.entries) > 128:
                    self.entries.popitem(last=False)
                self.pending.remove(uuid)
        return value
