import hashlib
import itertools
import json
import random
from pathlib import Path

import pytest
from mithril_web import parties
from mithril_web.parties import (
    CLASSES,
    JOIN_WINDOW,
    NO_SHOW_BAN,
    PRESENCE_GRACE,
    Finder,
    PartyError,
    failures,
    overflow_level,
    player_stats,
    requirements,
    validate_rules,
)
from mithril_web.player_card import CATACOMBS_XP, catacombs_level

ROLES = list(CLASSES)
NO_RULES = {"shared": {}, "per_class": {}, "exempt": []}


def stats(cata=51, mp=1380, level=50, m7_s_plus=331_000, solo=365_000, terms=43_000):
    return {
        "catacombs": cata,
        "class_levels": dict.fromkeys(CLASSES, float(level)),
        "magical_power": mp,
        "s_plus_ms": {"F7": 268_000, "M7": m7_s_plus},
        "solo_ms": {"F7": None, "M7": solo},
        "terminals_ms": {"F7": None, "M7": terms},
        "ss_ms": None,
    }


@pytest.fixture
def world():
    now = [1000.0]
    finder = Finder(lambda: now[0], rng=random.Random(7))

    def join(name, **kwargs):
        uuid = hashlib.md5(name.encode()).hexdigest()  # synthetic, stable per test name
        finder.seen(uuid, name, "web")
        finder.set_stats(uuid, stats(**kwargs))
        return uuid

    def lead(name, leader_class="mage", rules=NO_RULES, blocked=None, **kwargs):
        uuid = join(name, **kwargs)
        finder.publish(uuid, "M7", leader_class, ROLES, False, rules, blocked or {})
        return uuid, finder.players[uuid].party

    return finder, now, join, lead


def kinds(finder, uuid):
    return [notice["kind"] for notice in finder.players[uuid].notices]


def test_rules_combine_shared_and_class_rules_with_exemption_and_missing_values():
    rules = validate_rules(
        {
            "shared": {"catacombs": 48, "magical_power": 1300},
            "per_class": {"healer": {"catacombs": 52, "class_level": 45}, "tank": {}},
            "exempt": ["tank"],
        }
    )
    assert rules["per_class"] == {"healer": {"catacombs": 52, "class_level": 45}}
    assert requirements(rules, "healer") == {
        "catacombs": 52,
        "magical_power": 1300,
        "class_level": 45,
    }
    assert requirements(rules, "tank") == {"magical_power": 1300}
    player = stats(cata=51)
    assert [f["metric"] for f in failures(rules, "healer", player, "M7")] == ["catacombs"]
    assert failures(rules, "tank", player, "M7") == []
    # Missing data never passes an enabled rule, including the not-yet-tracked SS.
    ss_rule = validate_rules({"shared": {"ss_ms": 14_000}})
    assert failures(ss_rule, "healer", player, "M7")[0]["value"] is None


@pytest.mark.parametrize(
    "rules",
    [
        {"shared": {"speed": 1}},
        {"shared": {"catacombs": 0}},
        {"shared": {"catacombs": 1001}},
        {"shared": {"catacombs": True}},
        {"shared": {"ss_ms": 20_001}},
        {"per_class": {"wizard": {}}},
        {"exempt": ["wizard"]},
    ],
)
def test_invalid_rules_are_refused(rules):
    with pytest.raises(PartyError, match="invalid_rules"):
        validate_rules(rules)


def test_player_stats_merge_selected_profile_and_mod_records():
    summary = {
        "catacombs": {"level": 50.0, "experience": sum(CATACOMBS_XP) + 240_000_000},
        "class_levels": {"healer": 51.5},
        "magical_power": 1400,
        "floors": [{"floor": "M7", "s_plus_ms": 330_000}, {"floor": "F7", "s_plus_ms": None}],
    }
    records = [
        {"floor": "M7", "kind": "solo_clear", "real_ms": 360_000, "ticks": 7200},
        {"floor": "F7", "kind": "terminals", "real_ms": 40_000, "ticks": 800},
    ]
    result = player_stats(summary, records)
    assert result["catacombs"] == 51.2  # overflow past 50
    assert overflow_level(97_559_640) == catacombs_level(97_559_640)
    assert overflow_level(None) is None
    assert result["class_levels"]["healer"] == 51.5
    assert result["class_levels"]["tank"] is None
    assert result["s_plus_ms"] == {"F7": None, "M7": 330_000}
    assert result["solo_ms"]["M7"] == 360_000
    assert result["terminals_ms"]["F7"] == 40_000
    assert result["ss_ms"] is None


def test_manual_reserve_checks_rules_blocks_and_one_slot_at_a_time(world):
    finder, now, join, lead = world
    rules = {"shared": {"catacombs": 50}, "per_class": {}, "exempt": []}
    grim = join("Grim")
    _, party = lead("Noctis", rules=rules, blocked={grim: "Grim"})
    low = join("Low", cata=44)
    ok = join("Sable")
    with pytest.raises(PartyError, match="not_eligible"):
        finder.reserve(low, party, "healer")
    with pytest.raises(PartyError, match="not_found"):
        finder.reserve(grim, party, "healer")
    with pytest.raises(PartyError, match="slot_taken"):
        finder.reserve(ok, party, "mage")
    finder.reserve(ok, party, "healer")
    assert kinds(finder, ok)[-1] == "reserved"
    with pytest.raises(PartyError, match="in_party"):
        finder.reserve(ok, party, "tank")
    other = join("Other")
    with pytest.raises(PartyError, match="slot_taken"):
        finder.reserve(other, party, "healer")


def test_looking_places_closest_to_full_then_faster_average(world):
    finder, now, join, lead = world
    _, slow = lead("Slow", m7_s_plus=340_000)
    _, fast = lead("Fast", m7_s_plus=300_000)
    _, fuller = lead("Fuller", m7_s_plus=350_000)
    finder.reserve(join("Extra"), fuller, "archer")
    # Fuller has fewer open slots, so it wins despite the slowest average.
    first = join("First")
    finder.look(first, "M7", ["healer"], None)
    assert finder.players[first].party == fuller
    assert kinds(finder, first)[-1] == "placed"
    # Equal open slots: the faster average S+ PB wins.
    second = join("Second")
    finder.look(second, "M7", ["healer"], None)
    assert finder.players[second].party == fast
    assert slow in finder.parties


def test_team_limit_skips_slow_parties_but_manual_reserve_still_works(world):
    finder, now, join, lead = world
    _, slow = lead("Slow", m7_s_plus=352_000)
    picky = join("Picky")
    finder.look(picky, "M7", ["healer"], 340_000)
    assert finder.players[picky].party is None
    assert finder.players[picky].looking
    finder.reserve(picky, slow, "healer")
    assert finder.players[picky].party == slow
    assert finder.players[picky].looking is None


def test_publishing_fills_waiting_lookers_in_look_order(world):
    finder, now, join, lead = world
    early = join("Early")
    finder.look(early, "M7", ["healer"], None)
    now[0] += 1
    late = join("Late")
    finder.look(late, "M7", ["healer", "tank"], None)
    _, party = lead("Noctis")
    assert finder.players[early].party == party
    assert finder.players[late].party == party
    roles = {slot["member"]: slot["role"] for slot in finder.parties[party].slots}
    assert roles[early] == "healer"
    assert roles[late] == "tank"


def test_edits_never_remove_members_and_refill_new_matches(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    member = join("Sable", mp=1380)
    finder.reserve(member, party, "healer")
    strict = {"shared": {"magical_power": 1400}, "per_class": {}, "exempt": []}
    finder.edit(leader, strict, [], {})
    assert finder.players[member].party == party
    with pytest.raises(PartyError, match="not_leader"):
        finder.edit(member, strict, [], {})
    strong = join("Strong", mp=1500)
    finder.look(strong, "M7", ["tank"], None)
    assert finder.players[strong].party == party


def test_leader_leaving_transfers_to_a_member_and_last_member_drops_the_party(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    member = join("Sable")
    finder.reserve(member, party, "healer")
    finder.leave(leader)
    assert finder.parties[party].leader == member
    assert "leader_now" in kinds(finder, member)
    assert finder.parties[party].open_roles() == ["archer", "berserk", "mage", "tank"]
    finder.leave(member)
    assert party not in finder.parties


def test_unlist_frees_every_member(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    member = join("Sable")
    finder.reserve(member, party, "healer")
    finder.unlist(leader)
    assert party not in finder.parties
    assert finder.players[member].party is None
    assert kinds(finder, member)[-1] == "party_closed"


def test_remove_can_block_and_frees_the_slot(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    member = join("Sable")
    finder.reserve(member, party, "healer")
    with pytest.raises(PartyError, match="not_member"):
        finder.remove(leader, leader, False)
    finder.remove(leader, member, True)
    assert finder.players[member].party is None
    assert finder.parties[party].blocked == {member: "Sable"}
    with pytest.raises(PartyError, match="not_found"):
        finder.reserve(member, party, "healer")


def test_sixty_second_grace_stops_looking_and_releases_slots_without_a_ban(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    holder = join("Holder")
    finder.reserve(holder, party, "healer")
    looker = join("Looker")
    finder.look(looker, "F7", ["tank"], None)
    now[0] += PRESENCE_GRACE - 1
    finder.seen(leader, "Noctis", "web")
    finder.sweep()
    assert finder.players[holder].party == party
    assert finder.players[looker].looking
    now[0] += 2
    finder.seen(leader, "Noctis", "web")
    finder.sweep()
    assert finder.players[holder].party is None
    assert finder.players[holder].banned_until == 0
    assert finder.players[looker].looking is None
    assert kinds(finder, looker)[-1] == "stopped_looking"


def test_offline_leader_before_full_hands_over_or_disbands(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    member = join("Sable")
    finder.reserve(member, party, "healer")
    now[0] += PRESENCE_GRACE + 1
    finder.seen(member, "Sable", "web")
    finder.sweep()
    assert finder.parties[party].leader == member
    now[0] += PRESENCE_GRACE + 1
    finder.sweep()
    assert party not in finder.parties


def fill(
    finder, join, party, names=("A", "B", "H", "T"), roles=("archer", "berserk", "healer", "tank")
):
    members = []
    for name, role in zip(names, roles, strict=True):
        uuid = join(name)
        finder.reserve(uuid, party, role)
        members.append(uuid)
    return members


def test_full_party_waits_for_confirmed_hypixel_roster_not_just_game_presence(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    members = fill(finder, join, party)
    assert all("party_full" in kinds(finder, uuid) for uuid in [leader, *members])
    for uuid in [leader, *members[:-1]]:
        finder.seen(uuid, "x", "mod")
    assert party in finder.parties
    finder.seen(members[-1], "T", "mod")
    assert party in finder.parties
    assert finder.parties[party].full_since is not None
    with pytest.raises(PartyError, match="not_leader"):
        finder.confirm_joined(members[0], party, [leader, *members])
    with pytest.raises(PartyError, match="roster_mismatch"):
        finder.confirm_joined(leader, party, [leader, *members[:-1]])
    finder.confirm_joined(leader, party, [leader, *members])
    assert finder.parties[party].completed
    formed = finder.players[leader].notices[-1]
    assert formed["kind"] == "party_joined"
    assert len(formed["roster"]) == 5
    assert all(finder.players[uuid].party == party for uuid in [leader, *members])


def test_no_shows_are_removed_banned_and_their_slot_relisted(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    members = fill(finder, join, party)
    waiting = join("Waiting")
    finder.look(waiting, "M7", ["tank"], None)
    for uuid in [leader, *members[:-1]]:
        finder.seen(uuid, "x", "mod")
    # Offline in both site and game after filling: the join window applies, not the grace.
    now[0] += JOIN_WINDOW - 5
    for uuid in [leader, *members[:-1], waiting]:
        finder.seen(uuid, "x", "mod" if uuid != waiting else "web")
    finder.sweep()
    assert finder.players[members[-1]].party == party
    now[0] += 10
    for uuid in [leader, *members[:-1], waiting]:
        finder.seen(uuid, "x", "mod" if uuid != waiting else "web")
    finder.sweep()
    no_show = finder.players[members[-1]]
    assert no_show.party is None
    assert no_show.banned_until == now[0] + NO_SHOW_BAN
    assert no_show.notices[-1]["reason"] == "no_show"
    # The slot reopened and the waiting looker filled it; the others stay.
    assert finder.players[waiting].party == party
    assert all(finder.players[uuid].party == party for uuid in [leader, *members[:-1]])
    with pytest.raises(PartyError, match="banned"):
        finder.look(no_show.uuid, "M7", ["tank"], None)
    now[0] += NO_SHOW_BAN
    finder.seen(no_show.uuid, "T", "web")
    finder.look(no_show.uuid, "F7", ["tank"], None)


def test_game_presence_alone_is_not_tracked_and_idle_players_are_forgotten(world):
    finder, now, join, lead = world
    assert finder.seen("f" * 32, "Stranger", "mod") is None
    assert "f" * 32 not in finder.players
    idle = join("Idle")
    now[0] += parties.IDLE_FORGET + 1
    finder.sweep()
    assert idle not in finder.players


def test_leader_counts_are_throttled_and_only_while_leader_is_online(world):
    finder, now, join, lead = world
    rules = {"shared": {"catacombs": 50}, "per_class": {}, "exempt": []}
    leader, party = lead("Noctis", rules=rules)
    finder.reserve(join("Holder"), party, "healer")  # healer taken before lookers arrive
    for name, cata in (("Ok", 52), ("Low", 40)):
        uuid = join(name, cata=cata)
        finder.look(uuid, "M7", ["tank"], 300_000)
    finder.sweep()
    counts = finder.parties[party].counts
    assert counts["roles"]["tank"] == {"looking": 2, "qualify": 0}  # team too slow for both
    finder.players[leader].version = 0
    finder.sweep()  # throttled: nothing recomputed within the interval
    assert finder.players[leader].version == 0


def test_capacity_limits_are_enforced(world, monkeypatch):
    finder, now, join, lead = world
    monkeypatch.setattr(parties, "MAX_PARTIES", 1)
    lead("One")
    with pytest.raises(PartyError, match="capacity"):
        lead("Two")
    monkeypatch.setattr(parties, "MAX_PLAYERS", len(finder.players))
    with pytest.raises(PartyError, match="capacity"):
        finder.seen("e" * 32, "Late", "web")


def test_personal_view_shows_leader_only_fields_and_deadlines(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis", blocked={"c" * 32: "Grim"})
    member = join("Sable")
    finder.reserve(member, party, "healer")
    mine = finder.personal(leader)["party"]
    theirs = finder.personal(member)["party"]
    assert mine["you_lead"]
    assert mine["blocked"] == [{"uuid": "c" * 32, "name": "Grim"}]
    assert not theirs["you_lead"]
    assert "blocked" not in theirs
    assert theirs["join_deadline"] is None
    fill(finder, join, party, names=("A", "B", "T"), roles=("archer", "berserk", "tank"))
    assert finder.personal(member)["party"]["join_deadline"] == now[0] + JOIN_WINDOW


def test_changed_players_are_reported_for_waking(world):
    finder, now, join, lead = world
    leader, party = lead("Noctis")
    finder.drain()
    member = join("Sable")
    finder.drain()
    finder.reserve(member, party, "healer")
    assert finder.drain() == {leader, member}
    assert finder.drain() == set()


CONTRACT = Path(__file__).resolve().parents[2] / "contracts/party-v1.json"


def contract_scenario(monkeypatch):
    """Synthetic accounts only; shared with the frontend through contracts/party-v1.json."""
    ids = itertools.count(1)
    monkeypatch.setattr(parties.secrets, "token_urlsafe", lambda _: "party0000001")
    monkeypatch.setattr(parties.secrets, "token_hex", lambda _: f"n{next(ids):011d}")
    now = [1000.0]
    finder = Finder(lambda: now[0], rng=random.Random(1), epoch="fixture")
    leader, joiner = "0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"
    for uuid, name, data in (
        (
            leader,
            "Noctis",
            stats(cata=54.0, mp=1520, m7_s_plus=318_000, solo=352_000, terms=41_000),
        ),
        (joiner, "Sable", stats(cata=51.0, mp=1380, m7_s_plus=331_000, solo=None, terms=None)),
    ):
        finder.seen(uuid, name, "web")
        data["class_levels"]["healer"] = 49.5
        finder.set_stats(uuid, data)
    rules = {
        "shared": {"catacombs": 48, "magical_power": 1300},
        "per_class": {"healer": {"class_level": 45}},
        "exempt": [],
    }
    party_id = finder.publish(leader, "M7", "mage", ROLES, False, rules, {"c" * 32: "Grim"})
    now[0] = 1060.0
    finder.reserve(joiner, party_id, "healer")
    party = finder.parties[party_id]
    return {
        "state": finder.personal(joiner),
        "leader_state": finder.personal(leader),
        "listings": {"version": 1, "floor": "M7", "parties": [finder.listing(party)]},
        "detail": {"version": 1, **finder.detail(party)},
    }


def test_shared_contract(monkeypatch):
    assert contract_scenario(monkeypatch) == json.loads(CONTRACT.read_text())


def test_blocks_follow_the_uuid_across_renames_and_edits_keep_or_add(world):
    finder, now, join, lead = world
    grim = join("Grim")
    leader, party = lead("Noctis", blocked={grim: "Grim"})
    finder.seen(grim, "Renamed", "web")
    with pytest.raises(PartyError, match="not_found"):
        finder.reserve(grim, party, "healer")
    # Someone else taking the old name is not blocked.
    newcomer = "f" * 32
    finder.seen(newcomer, "Grim", "web")
    finder.set_stats(newcomer, stats())
    finder.reserve(newcomer, party, "healer")
    other = "d" * 32
    finder.edit(leader, NO_RULES, [grim, "e" * 32], {other: "Other"})
    assert finder.parties[party].blocked == {grim: "Grim", other: "Other"}
    finder.edit(leader, NO_RULES, [], {})
    assert finder.parties[party].blocked == {}
    with pytest.raises(PartyError, match="invalid_blocked"):
        finder.edit(leader, NO_RULES, [], {"not-a-uuid": "x"})


def test_presence_is_current_and_a_full_party_reopens_with_the_same_id(world):
    finder, now, join, lead = world
    leader, party = lead("Leader")
    members = fill(finder, join, party)
    for uuid in [leader, *members[:-1]]:
        finder.seen(uuid, finder.players[uuid].name, "mod")
    now[0] += PRESENCE_GRACE + 1
    finder.sweep()
    finder.seen(members[-1], finder.players[members[-1]].name, "mod")
    assert party in finder.parties
    assert sum(finder.personal(leader)["party"]["joined"]) == 1
    finder.leave(members[-1])
    assert finder.parties[party].full_since is None
    assert finder.parties[party].open_roles() == ["tank"]


@pytest.mark.parametrize("source", ["web", "mod"])
def test_new_leader_must_have_current_web_or_mod_presence(world, source):
    finder, now, join, lead = world
    leader, party = lead("Leader")
    offline = join("Offline")
    online = join("Online")
    finder.reserve(offline, party, "healer")
    finder.reserve(online, party, "tank")
    now[0] += PRESENCE_GRACE + 1
    finder.seen(online, "Online", source)
    finder.leave(leader)
    assert finder.parties[party].leader == online


def test_leader_leaving_without_an_online_successor_releases_everyone(world):
    finder, now, join, lead = world
    leader, party = lead("Leader")
    member = join("Offline")
    finder.reserve(member, party, "healer")
    now[0] += PRESENCE_GRACE + 1
    finder.leave(leader)
    assert party not in finder.parties
    assert finder.players[member].party is None
    assert finder.players[member].notices[-1]["kind"] == "party_closed"


def test_recreated_player_has_a_different_state_id(world):
    finder, now, join, _ = world
    uuid = join("Idle")
    before = finder.personal(uuid)["state_id"]
    now[0] += parties.IDLE_FORGET + 1
    finder.sweep()
    join("Idle")
    assert finder.personal(uuid)["state_id"] != before
