import pytest
from mithril_web.curator import catalog, clues, compare, families, guess_names


def item(identifier, name, **fields):
    return {"id": identifier, "name": name, "tier": "EPIC", **fields}


SYNTH_V2 = item(
    "SYNTHESIZER_V2",
    "Synthesizer v2",
    category="NECKLACE",
    npc_sell_price=9280,
    requirements=[{"type": "SKILL", "skill": "COMBAT", "level": 22}],
    museum_data={
        "category": "COMBAT",
        "game_stage": "EXPERT",
        "parent": {"SYNTHESIZER_V2": "SYNTHESIZER_V3"},
    },
)
SYNTH_V3 = item(
    "SYNTHESIZER_V3",
    "Synthesizer v3",
    category="NECKLACE",
    npc_sell_price=17440,
    requirements=[{"type": "SKILL", "skill": "COMBAT", "level": 22}],
    museum_data={"category": "COMBAT", "game_stage": "PROFESSIONAL", "parent": {}},
)


def test_clues_read_every_column_from_the_items_list():
    assert clues(SYNTH_V3) == {
        "rarity": "EPIC",
        "type": "NECKLACE",
        "museum": "COMBAT",
        "stage": "PROFESSIONAL",
        "requirements": {"SKILL:COMBAT": 22},
        "soulbound": None,
        "origin": None,
        "npc": 17440,
        "length": 14,
    }
    elevator = clues(
        item(
            "ANCIENT_ELEVATOR",
            "§dAncient Elevator",
            tier="SPECIAL",
            museum=True,
            origin="RIFT",
            soulbound="COOP",
        )
    )
    assert elevator["museum"] == "SPECIAL"
    assert elevator["stage"] is None
    assert (elevator["origin"], elevator["soulbound"], elevator["length"]) == ("RIFT", "COOP", 16)
    assert elevator["npc"] is None


def test_requirements_normalise_types_levels_and_nested_choices():
    values = clues(
        item(
            "X",
            "X",
            requirements=[
                {"type": "SLAYER", "slayer_boss_type": "spider", "level": 7},
                {"type": "HEART_OF_THE_MOUNTAIN", "tier": 5},
                {"type": "ANY_OF", "requirements": [{"type": "HEART_OF_THE_MOUNTAIN", "tier": 2}]},
                {"type": "CRIMSON_ISLE_REPUTATION", "faction": "BARBARIANS", "reputation": 12000},
                "not a requirement",
            ],
            catacombs_requirements=[
                {"type": "DUNGEON_SKILL", "dungeon_type": "CATACOMBS", "level": 30}
            ],
        )
    )
    assert values["requirements"] == {
        "SLAYER:SPIDER": 7,
        "HEART_OF_THE_MOUNTAIN": 5,
        "ANY_OF": None,
        "CRIMSON_ISLE_REPUTATION:BARBARIANS": 12000,
        "DUNGEON_SKILL:CATACOMBS": 30,
    }


def test_catalog_filters_guesses_and_answers():
    items = [
        SYNTH_V2,
        SYNTH_V3,
        item("TEST_SWORD", "Sword of the Stars 3000", tier="UNOBTAINABLE"),
        item("NO_TIER", "Mystery", tier=None),
        item("HIDDEN", "Hidden", hide_from_api=True),
        item("SKIN", "Snowman Minion Skin", category="COSMETIC"),
        item("SNOW_PERSONALITY", "Snow Minion Skin"),
        item("PET_SKIN_SHEEP", "Sheep Skin", npc_sell_price=1),
        item("SLOTH_HAT", "Sloth Hat of Celebration", npc_sell_price=2),
        item("BLADE_A", "Daedalus Blade", npc_sell_price=3),
        item("BLADE_B", "Daedalus Blade", npc_sell_price=4),
        item("TWIN_A", "Twin One", npc_sell_price=5),
        item("TWIN_B", "Twin Two", npc_sell_price=5),
        "not an item",
    ]
    entries = catalog(items)
    assert "TEST_SWORD" not in entries and "NO_TIER" not in entries and "HIDDEN" not in entries
    candidates = {identifier for identifier, entry in entries.items() if entry["candidate"]}
    assert candidates == {"SYNTHESIZER_V2", "SYNTHESIZER_V3"}
    assert entries["SYNTHESIZER_V2"]["family"] == entries["SYNTHESIZER_V3"]["family"]
    assert entries["SKIN"]["cosmetic"] and entries["SNOW_PERSONALITY"]["cosmetic"]
    names = guess_names(entries)
    assert names["Daedalus Blade"] == "BLADE_A"
    assert names["Twin One"] == "TWIN_A"


def test_families_join_whole_upgrade_chains():
    chain = families(
        [
            {"museum_data": {"parent": {"C_1": "C_2"}}},
            {"museum_data": {"parent": {"C_3": "C_4"}}},
            {"museum_data": {"parent": {"C_2": "C_3"}}},
            {"museum_data": {"parent": {"bad": 1}}},
            {"museum_data": None},
        ]
    )
    assert set(chain) == {"C_1", "C_2", "C_3", "C_4"}
    assert set(chain.values()) == {"C_1"}


def test_a_correct_guess_matches_every_column():
    answer = clues(SYNTH_V3)
    result = compare(answer, answer, 5_000_000, 5_000_000)
    assert all(column == {"match": "exact"} for column in result.values())
    assert len(result) == 10


def test_feedback_marks_partial_matches_and_points_towards_the_answer():
    answer = clues(SYNTH_V3)
    sibling = compare(clues(SYNTH_V2), answer, 3_100_000, 5_400_000)
    assert sibling["stage"] == {"match": "none", "arrow": "up"}
    assert sibling["npc"] == {"match": "none", "arrow": "up"}
    assert sibling["market"] == {"match": "none", "arrow": "up"}
    assert sibling["requirements"] == {"match": "exact"}
    sword = item(
        "HYPERION",
        "Hyperion",
        tier="LEGENDARY",
        category="SWORD",
        soulbound="SOLO",
        npc_sell_price=17000,
        requirements=[
            {"type": "SKILL", "skill": "COMBAT", "level": 30},
            {"type": "DUNGEON_SKILL", "dungeon_type": "CATACOMBS", "level": 30},
        ],
    )
    result = compare(clues(sword), answer, 900_000_000, 5_400_000)
    assert result["rarity"] == {"match": "none", "arrow": "down"}
    assert result["type"] == {"match": "none"}
    assert result["museum"] == {"match": "none"}
    assert result["stage"] == {"match": "none"}
    assert result["requirements"] == {"match": "partial", "arrow": "down"}
    assert result["soulbound"] == {"match": "none"}
    assert result["npc"] == {"match": "exact"}
    assert result["market"] == {"match": "none", "arrow": "down"}
    assert result["length"] == {"match": "none", "arrow": "up"}


@pytest.mark.parametrize(
    "guess,answer,expected",
    [
        ({}, {}, {"match": "exact"}),
        ({"SKILL:COMBAT": 20}, {"SLAYER:WOLF": 3}, {"match": "none"}),
        ({"SKILL:COMBAT": 20, "SLAYER:WOLF": 3}, {"SKILL:COMBAT": 20}, {"match": "partial"}),
        ({"ANY_OF": None}, {"ANY_OF": None, "GARDEN_LEVEL": 5}, {"match": "partial"}),
    ],
)
def test_requirement_overlap(guess, answer, expected):
    base = clues(SYNTH_V3)
    result = compare({**base, "requirements": guess}, {**base, "requirements": answer})
    assert result["requirements"] == expected


def test_soulbound_and_missing_values():
    base = clues(SYNTH_V3)
    solo, coop = {**base, "soulbound": "SOLO"}, {**base, "soulbound": "COOP"}
    assert compare(solo, coop)["soulbound"] == {"match": "partial"}
    assert compare(solo, base)["soulbound"] == {"match": "none"}
    assert compare(base, base)["market"] == {"match": "exact"}
    assert compare(base, base, None, 10)["market"] == {"match": "none"}
    assert compare({**base, "rarity": "SUPREME"}, {**base, "rarity": "DIVINE"})["rarity"] == {
        "match": "exact"
    }
    assert compare({**base, "stage": None}, base)["stage"] == {"match": "none"}
