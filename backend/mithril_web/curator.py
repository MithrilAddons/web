"""Curator clue engine: what each item reveals and how a guess compares with the answer.

Everything here is derived from Hypixel's public items list; market value is a daily
snapshot kept elsewhere and passed in.
"""

import json
import re

RARITIES = [
    "COMMON",
    "UNCOMMON",
    "RARE",
    "EPIC",
    "LEGENDARY",
    "MYTHIC",
    "DIVINE",
    "SPECIAL",
    "VERY_SPECIAL",
]
# Hypixel renamed Supreme to Divine; the one remaining Supreme item ranks with Divine.
RANK = {name: index for index, name in enumerate(RARITIES)} | {"SUPREME": RARITIES.index("DIVINE")}
STAGES = ["STARTER", "AMATEUR", "INTERMEDIATE", "SKILLED", "EXPERT", "PROFESSIONAL", "MASTER"]
STAGE_RANK = {name: index for index, name in enumerate(STAGES)}
COLUMNS = (
    "rarity",
    "type",
    "museum",
    "stage",
    "requirements",
    "soulbound",
    "origin",
    "market",
    "npc",
    "length",
)
QUALIFIERS = (
    "skill",
    "slayer_boss_type",
    "dungeon_type",
    "collection",
    "faction",
    "chapter",
    "trophy_type",
    "mode",
    "rabbit",
    "kuudra_tier",
)
LEVELS = ("level", "tier", "reputation")
FORMATTING = re.compile(r"§[0-9A-FK-OR]", re.I)


def clean(value):
    return FORMATTING.sub("", value).strip() if isinstance(value, str) else ""


def number(value):
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def requirement(entry):
    kind = str(entry.get("type", ""))
    qualifier = next((entry[k] for k in QUALIFIERS if isinstance(entry.get(k), str)), None)
    level = next((entry[k] for k in LEVELS if isinstance(entry.get(k), int)), None)
    key = f"{kind}:{qualifier.upper()}" if qualifier else kind
    # Nested choices have no single level to compare.
    return key, None if kind in ("ANY_OF", "ONE_OF") else level


def museum_category(item):
    museum = item.get("museum_data")
    if isinstance(museum, dict):
        return museum.get("category")
    # Special items like the Ancient Elevator are flagged without museum data.
    return "SPECIAL" if item.get("museum") is True else None


def clues(item):
    """The clue values of one items-list entry, market value excluded."""
    museum = item.get("museum_data")
    requirements = {}
    for entry in [*item.get("requirements", []), *item.get("catacombs_requirements", [])]:
        if isinstance(entry, dict):
            key, level = requirement(entry)
            requirements[key] = level
    npc = number(item.get("npc_sell_price"))
    return {
        "rarity": item.get("tier"),
        "type": item.get("category"),
        "museum": museum_category(item),
        "stage": museum.get("game_stage") if isinstance(museum, dict) else None,
        "requirements": requirements,
        "soulbound": item.get("soulbound"),
        "origin": item.get("origin"),
        "npc": npc if npc and npc > 0 else None,
        "length": len(clean(item.get("name"))),
    }


def cosmetic(item):
    identifier, name = item.get("id", ""), clean(item.get("name"))
    return (
        item.get("category") == "COSMETIC"
        or identifier.endswith("_PERSONALITY")
        or identifier.startswith("PET_SKIN_")
        or "Hat of Celebration" in name
    )


def guessable(item):
    return (
        bool(clean(item.get("name")))
        and isinstance(item.get("id"), str)
        and item.get("tier") in RANK
        and not item.get("hide_from_api")
    )


def families(items):
    """Upgrade chains from the museum parent links, keyed by item ID."""
    parent = {}

    def root(identifier):
        while parent.get(identifier, identifier) != identifier:
            identifier = parent[identifier]
        return identifier

    for item in items:
        links = (item.get("museum_data") or {}).get("parent") or {}
        for child, upgrade in links.items():
            if isinstance(child, str) and isinstance(upgrade, str):
                a, b = root(child), root(upgrade)
                if a != b:
                    parent[max(a, b)] = min(a, b)
                parent.setdefault(min(a, b), min(a, b))
    return {identifier: root(identifier) for identifier in parent}


def signature(values):
    return json.dumps(values, sort_keys=True)


def catalog(items):
    """Every item's clues, whether it can be guessed and whether it can be an answer."""
    items = sorted(
        (i for i in items if isinstance(i, dict) and guessable(i)), key=lambda i: i["id"]
    )
    family = families(items)
    entries = {
        item["id"]: {
            "name": clean(item["name"]),
            "clues": clues(item),
            "family": family.get(item["id"]),
            "cosmetic": cosmetic(item),
        }
        for item in items
    }
    names, looks = {}, {}
    for entry in entries.values():
        names[entry["name"]] = names.get(entry["name"], 0) + 1
        key = signature(entry["clues"])
        looks[key] = looks.get(key, 0) + 1
    for entry in entries.values():
        # A shared name can't be told apart by typing it; identical clues can't by playing.
        entry["candidate"] = (
            not entry["cosmetic"]
            and names[entry["name"]] == 1
            and looks[signature(entry["clues"])] == 1
        )
    return entries


def guess_names(entries):
    """One ID per name for autocomplete; duplicated names resolve to their first ID."""
    result = {}
    for identifier in sorted(entries):
        result.setdefault(entries[identifier]["name"], identifier)
    return result


def ordered(guess, answer, rank):
    if guess not in rank or answer not in rank:
        return {"match": "exact" if guess == answer else "none"}
    if rank[guess] == rank[answer]:
        return {"match": "exact"}
    return {"match": "none", "arrow": "up" if rank[answer] > rank[guess] else "down"}


def length(guess, answer):
    if guess == answer:
        return {"match": "exact"}
    return {"match": "none", "arrow": "up" if answer > guess else "down"}


def numeric(guess, answer):
    if guess is None or answer is None:
        return {"match": "exact" if guess == answer else "none"}
    if abs(guess - answer) <= 0.1 * answer:
        return {"match": "exact"}
    return {"match": "none", "arrow": "up" if answer > guess else "down"}


def requirements(guess, answer):
    if guess == answer:
        return {"match": "exact"}
    shared = guess.keys() & answer.keys()
    if not shared:
        return {"match": "none"}
    result = {"match": "partial"}
    if len(shared) == 1:
        key = next(iter(shared))
        low, high = guess[key], answer[key]
        if isinstance(low, int) and isinstance(high, int) and low != high:
            result["arrow"] = "up" if high > low else "down"
    return result


def soulbound(guess, answer):
    if guess == answer:
        return {"match": "exact"}
    # Solo and Co-op are both soulbound, just to a different owner.
    return {"match": "partial" if guess and answer else "none"}


def compare(guess, answer, guess_market=None, answer_market=None):
    """Feedback per column for one guess; an up arrow means the answer is higher."""
    return {
        "rarity": ordered(guess["rarity"], answer["rarity"], RANK),
        "type": {"match": "exact" if guess["type"] == answer["type"] else "none"},
        "museum": {"match": "exact" if guess["museum"] == answer["museum"] else "none"},
        "stage": ordered(guess["stage"], answer["stage"], STAGE_RANK),
        "requirements": requirements(guess["requirements"], answer["requirements"]),
        "soulbound": soulbound(guess["soulbound"], answer["soulbound"]),
        "origin": {"match": "exact" if guess["origin"] == answer["origin"] else "none"},
        "market": numeric(guess_market, answer_market),
        "npc": numeric(guess["npc"], answer["npc"]),
        "length": length(guess["length"], answer["length"]),
    }
