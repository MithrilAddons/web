"""Event-loop-owned party finder: listings, held slots, automatic placement and timers.

All state is in memory and only touched from the asyncio event loop, so it needs no
locks. Work is incremental so a small server can carry ~2000 players: placement only
reconsiders the player or party an event touched, and the periodic sweep is linear in
known players. Network lookups (Hypixel stats, mod records) happen before calling in.
"""

import random
import re
import secrets
import time
from collections import deque

from .player_card import CATACOMBS_XP, catacombs_level

CLASSES = ("archer", "berserk", "healer", "mage", "tank")
FLOORS = ("F7", "M7")
# name: (direction, largest accepted threshold)
METRICS = {
    "catacombs": ("min", 1000),  # overflow levels above 50 are common requirements
    "class_level": ("min", 50),
    "magical_power": ("min", 10_000),
    "s_plus_ms": ("max", 7_200_000),
    "solo_ms": ("max", 7_200_000),
    "terminals_ms": ("max", 7_200_000),
    "ss_ms": ("max", 20_000),
}
PER_FLOOR = ("s_plus_ms", "solo_ms", "terminals_ms")
PRESENCE_GRACE = 60  # site and game both closed this long: stop looking / release the slot
JOIN_WINDOW = 300  # once full, everyone must be in game within this
NO_SHOW_BAN = 3600
IDLE_FORGET = 3600
COUNT_INTERVAL = 60  # leader "qualify" counts are the only per-party scan of lookers
COUNT_BUDGET = 0.02  # seconds of counting per sweep, oldest counts first
OVERFLOW_XP = 200_000_000  # community convention (e.g. SkyCrypt) per level after 50
MAX_PLAYERS = 4000
MAX_PARTIES = 800
MAX_BLOCKED = 100
NOTICES = 10


class PartyError(Exception):
    """A refused action. The code is part of the v1 wire format."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Player:
    __slots__ = (
        "uuid",
        "name",
        "web_seen",
        "mod_seen",
        "in_game",
        "stats",
        "looking",
        "party",
        "banned_until",
        "notices",
        "version",
        "state_id",
    )

    def __init__(self, uuid, name, state_id):
        self.uuid, self.name = uuid, name
        self.web_seen = self.mod_seen = float("-inf")
        self.in_game = False
        self.stats = None
        self.looking = None
        self.party = None
        self.banned_until = 0.0
        self.notices = deque(maxlen=NOTICES)
        self.version = 0
        self.state_id = state_id


class Party:
    __slots__ = (
        "id",
        "floor",
        "leader",
        "created",
        "rules",
        "checks",
        "blocked",
        "paused",
        "slots",
        "full_since",
        "counts",
        "counted_at",
        "public_version",
        "handoff_id",
        "invited_at",
        "accepted",
    )

    def __init__(self, floor, leader, created, rules, blocked, roles):
        self.id = secrets.token_urlsafe(9)
        self.floor, self.leader, self.created = floor, leader, created
        self.rules, self.blocked = rules, blocked
        self.checks = compile_checks(rules, floor)
        self.paused = False
        self.slots = [{"role": role, "member": None, "joined": False} for role in roles]
        self.full_since = None
        self.counts = None
        self.counted_at = float("-inf")
        self.public_version = 0
        self.handoff_id = secrets.token_urlsafe(9)
        self.invited_at = None
        self.accepted = set()

    def members(self):
        return [slot["member"] for slot in self.slots if slot["member"]]

    def open_roles(self):
        return [slot["role"] for slot in self.slots if not slot["member"]]


def overflow_level(experience):
    """Catacombs level without the cap at 50."""
    if experience is None:
        return None
    beyond = experience - sum(CATACOMBS_XP)
    return 50 + beyond / OVERFLOW_XP if beyond > 0 else catacombs_level(experience)


def player_stats(summary, mod_records):
    """Matching inputs from a Hypixel summary (selected profile) plus account-wide mod PBs."""
    floors = {row["floor"]: row for row in summary.get("floors", [])}
    stats = {
        "catacombs": overflow_level((summary.get("catacombs") or {}).get("experience")),
        "class_levels": {role: (summary.get("class_levels") or {}).get(role) for role in CLASSES},
        "magical_power": summary.get("magical_power"),
        "s_plus_ms": {floor: floors.get(floor, {}).get("s_plus_ms") for floor in FLOORS},
        "solo_ms": dict.fromkeys(FLOORS),
        "terminals_ms": dict.fromkeys(FLOORS),
        # One average of the last 20 F7/M7 runs; the mod does not report it yet.
        "ss_ms": None,
    }
    for record in mod_records:
        key = {"solo_clear": "solo_ms", "terminals": "terminals_ms"}.get(record["kind"])
        if key and record["floor"] in FLOORS:
            stats[key][record["floor"]] = record["real_ms"]
    return stats


def stat(stats, metric, role, floor):
    if stats is None:
        return None
    if metric == "class_level":
        return stats["class_levels"].get(role)
    value = stats[metric]
    return value.get(floor) if isinstance(value, dict) else value


def meets(metric, threshold, value):
    if value is None or value <= 0:
        return False
    return value >= threshold if METRICS[metric][0] == "min" else value <= threshold


def requirements(rules, role):
    """Shared rules (minus an exempt Catacombs level) and class rules; the stricter wins."""
    result = {
        metric: value
        for metric, value in rules["shared"].items()
        if not (metric == "catacombs" and role in rules["exempt"])
    }
    for metric, value in rules["per_class"].get(role, {}).items():
        current = result.get(metric)
        stricter = max if METRICS[metric][0] == "min" else min
        result[metric] = value if current is None else stricter(current, value)
    return result


def failures(rules, role, stats, floor):
    return [
        {"metric": metric, "threshold": threshold, "value": stat(stats, metric, role, floor)}
        for metric, threshold in requirements(rules, role).items()
        if not meets(metric, threshold, stat(stats, metric, role, floor))
    ]


def compile_checks(rules, floor):
    """Per role, flat (key, subkey, threshold, at_least) tuples for the hot matching path."""
    checks = {}
    for role in CLASSES:
        flat = []
        for metric, threshold in requirements(rules, role).items():
            if metric == "class_level":
                key, subkey = "class_levels", role
            else:
                key, subkey = metric, floor if metric in PER_FLOOR else None
            flat.append((key, subkey, threshold, METRICS[metric][0] == "min"))
        checks[role] = tuple(flat)
    return checks


def qualifies(checks, stats):
    for key, subkey, threshold, at_least in checks:
        value = stats[key]
        if subkey is not None:
            value = value.get(subkey)
        if value is None or value <= 0 or (value < threshold if at_least else value > threshold):
            return False
    return True


def _thresholds(values):
    if not isinstance(values, dict):
        raise PartyError("invalid_rules")
    for metric, value in values.items():
        if metric not in METRICS or type(value) is not int or not 1 <= value <= METRICS[metric][1]:
            raise PartyError("invalid_rules")
    return dict(values)


def validate_rules(rules):
    per_class = {}
    for role, values in rules.get("per_class", {}).items():
        if role not in CLASSES:
            raise PartyError("invalid_rules")
        if values := _thresholds(values):
            per_class[role] = values
    exempt = rules.get("exempt", [])
    if not isinstance(exempt, list) or not set(exempt) <= set(CLASSES):
        raise PartyError("invalid_rules")
    return {
        "shared": _thresholds(rules.get("shared", {})),
        "per_class": per_class,
        "exempt": sorted(set(exempt)),
    }


def validate_blocked(blocked):
    """Blocks are by UUID, so renaming never escapes one; names are only for display."""
    if not isinstance(blocked, dict) or len(blocked) > MAX_BLOCKED:
        raise PartyError("invalid_blocked")
    for uuid, name in blocked.items():
        if not isinstance(uuid, str) or not re.fullmatch(r"[0-9a-f]{32}", uuid):
            raise PartyError("invalid_blocked")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            raise PartyError("invalid_blocked")
    return dict(blocked)


class Finder:
    def __init__(self, clock, rng=None, *, epoch=None):
        self.clock = clock
        self.rng = rng or random.SystemRandom()
        self.players = {}
        self.parties = {}
        self.lookers = {floor: {} for floor in FLOORS}  # insertion order is look order
        self.floor_version = dict.fromkeys(FLOORS, 0)
        self.changed = set()
        self.epoch = epoch or secrets.token_hex(16)
        self.player_sequence = 0

    # -- bookkeeping ---------------------------------------------------------------

    def drain(self):
        """Players whose personal state changed since the last drain (to wake waiters)."""
        changed, self.changed = self.changed, set()
        return changed

    def _touch(self, player):
        player.version += 1
        self.changed.add(player.uuid)

    def _touch_party(self, party):
        party.public_version += 1
        self.floor_version[party.floor] += 1
        for uuid in party.members():
            self._touch(self.players[uuid])

    def _notice(self, player, kind, now, **data):
        player.notices.append({"id": secrets.token_hex(6), "kind": kind, "at": now, **data})
        self._touch(player)

    def _present(self, player, now):
        return max(player.web_seen, player.mod_seen) > now - PRESENCE_GRACE

    def seen(self, uuid, name, source, online=True):
        """Record a request from the website ("web") or the mod ("mod") for this account.

        Game presence alone never creates an entry: only finder users are tracked.
        """
        now = self.clock()
        player = self.players.get(uuid)
        if player is None:
            if source == "mod":
                return None
            if len(self.players) >= MAX_PLAYERS:
                raise PartyError("capacity")
            self.player_sequence += 1
            player = self.players[uuid] = Player(uuid, name, f"{self.epoch}:{self.player_sequence}")
        elif player.name != name:
            player.name = name
            self._touch(player)
        if source == "mod":
            player.mod_seen = now
            if player.in_game != online:
                player.in_game = online
                self._touch(player)
            party = self.parties.get(player.party)
            if party and party.full_since is not None:
                self._check_joined(party, now)
        else:
            player.web_seen = now
        return player

    def set_stats(self, uuid, stats):
        player = self.players[uuid]
        if stats is not None and stats != player.stats:
            player.stats = stats
            self._touch(player)
            if party := self.parties.get(player.party):
                self._touch_party(party)  # team averages in the listing

    def _get(self, uuid):
        player = self.players.get(uuid)
        if player is None:
            raise PartyError("unknown_player")
        return player

    def _led(self, uuid):
        player = self._get(uuid)
        party = self.parties.get(player.party)
        if not party or party.leader != uuid:
            raise PartyError("not_leader")
        return party

    # -- joining -------------------------------------------------------------------

    def look(self, uuid, floor, classes, max_team_s_plus_ms):
        now = self.clock()
        player = self._get(uuid)
        if player.banned_until > now:
            raise PartyError("banned")
        if player.party:
            raise PartyError("in_party")
        if player.stats is None:
            raise PartyError("stats_unavailable")
        if floor not in FLOORS or not classes or len(set(classes)) != len(classes):
            raise PartyError("invalid_search")
        if not set(classes) <= set(CLASSES):
            raise PartyError("invalid_search")
        limit = max_team_s_plus_ms
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 7_200_000):
            raise PartyError("invalid_search")
        self._stop_looking(player)
        player.looking = {"floor": floor, "classes": list(classes), "limit": limit, "since": now}
        self.lookers[floor][uuid] = player
        self._touch(player)
        self._place_player(player, now)

    def stop_looking(self, uuid):
        player = self._get(uuid)
        if player.looking:
            self._stop_looking(player)
            self._touch(player)

    def _stop_looking(self, player):
        if player.looking:
            self.lookers[player.looking["floor"]].pop(player.uuid, None)
            player.looking = None

    def reserve(self, uuid, party_id, role):
        now = self.clock()
        player = self._get(uuid)
        if player.banned_until > now:
            raise PartyError("banned")
        if player.party:
            raise PartyError("in_party")
        if player.stats is None:
            raise PartyError("stats_unavailable")
        party = self.parties.get(party_id)
        if not party or party.paused or uuid in party.blocked:
            raise PartyError("not_found")
        if party.full_since is not None:
            raise PartyError("party_full")
        if role not in party.open_roles():
            raise PartyError("slot_taken")
        if not qualifies(party.checks[role], player.stats):
            raise PartyError("not_eligible")
        self._seat(party, player, role, now, auto=False)

    def leave(self, uuid):
        now = self.clock()
        player = self._get(uuid)
        party = self.parties.get(player.party)
        if not party:
            raise PartyError("not_in_party")
        self._vacate(party, uuid, now, "left")
        if party.id in self.parties:
            self._fill_party(party, now)

    def team_s_plus(self, party):
        values = [
            stat(self.players[uuid].stats, "s_plus_ms", None, party.floor)
            for uuid in party.members()
        ]
        values = [value for value in values if value]
        return sum(values) / len(values) if values else None

    def _fit(self, party, player):
        """The first looking class this player can take in this party, or None."""
        if party.paused or party.full_since is not None:
            return None
        if player.uuid in party.blocked:
            return None
        looking = player.looking
        if looking["limit"] is not None:
            average = self.team_s_plus(party)
            if average is None or average > looking["limit"]:
                return None
        open_roles = party.open_roles()
        for role in looking["classes"]:
            if role in open_roles and qualifies(party.checks[role], player.stats):
                return role
        return None

    def _place_player(self, player, now):
        """Closest to full first; ties go to the faster average S+ PB."""
        best = None
        for party in self.parties.values():
            if party.floor != player.looking["floor"]:
                continue
            role = self._fit(party, player)
            if role is None:
                continue
            key = (len(party.open_roles()), self.team_s_plus(party) or float("inf"))
            if best is None or key < best[0]:
                best = (key, party, role)
        if best:
            self._seat(best[1], player, best[2], now, auto=True)

    def _fill_party(self, party, now):
        for player in list(self.lookers[party.floor].values()):
            if party.full_since is not None:
                return
            role = self._fit(party, player)
            if role:
                self._seat(party, player, role, now, auto=True)

    def _seat(self, party, player, role, now, auto):
        slot = next(s for s in party.slots if s["role"] == role and not s["member"])
        slot["member"], slot["joined"] = player.uuid, False
        self._stop_looking(player)
        player.party = party.id
        self._notice(player, "placed" if auto else "reserved", now, party=party.id, role=role)
        self._notice(self.players[party.leader], "member_joined", now, name=player.name, role=role)
        if not party.open_roles():
            party.full_since = now
            for uuid in party.members():
                self._notice(self.players[uuid], "party_full", now, party=party.id)
            self._check_joined(party, now)
        self._touch_party(party)

    # -- leading -------------------------------------------------------------------

    def publish(self, uuid, floor, leader_class, roles, allow_duplicates, rules, blocked):
        now = self.clock()
        player = self._get(uuid)
        if player.party:
            raise PartyError("in_party")
        if len(self.parties) >= MAX_PARTIES:
            raise PartyError("capacity")
        if floor not in FLOORS or len(roles) != 5 or not set(roles) <= set(CLASSES):
            raise PartyError("invalid_settings")
        if leader_class not in roles:
            raise PartyError("invalid_settings")
        if not allow_duplicates and sorted(roles) != sorted(CLASSES):
            raise PartyError("invalid_settings")
        party = Party(floor, uuid, now, validate_rules(rules), validate_blocked(blocked), roles)
        self._stop_looking(player)
        self.parties[party.id] = party
        slot = next(s for s in party.slots if s["role"] == leader_class)
        slot["member"] = uuid
        player.party = party.id
        self._touch_party(party)
        self._fill_party(party, now)
        return party.id

    def edit(self, uuid, rules, keep, add):
        """Existing members always keep their slots; the leader removes them by hand.

        `keep` lists already-blocked UUIDs to retain; `add` maps new UUIDs to names.
        """
        party = self._led(uuid)
        kept = {key: party.blocked[key] for key in keep if key in party.blocked}
        blocked = validate_blocked({**kept, **add})
        party.rules = validate_rules(rules)
        party.checks = compile_checks(party.rules, party.floor)
        party.blocked = blocked
        party.counted_at = float("-inf")
        self._touch_party(party)
        self._fill_party(party, self.clock())

    def pause(self, uuid, paused):
        party = self._led(uuid)
        if party.paused != paused:
            party.paused = paused
            self._touch_party(party)
            if not paused:
                self._fill_party(party, self.clock())

    def unlist(self, uuid):
        party = self._led(uuid)
        self._close(party, self.clock())

    def _close(self, party, now):
        for member in party.members():
            player = self.players[member]
            player.party = None
            self._notice(player, "party_closed", now, party=party.id)
        self._drop(party)

    def remove(self, uuid, member, block):
        party = self._led(uuid)
        if member == uuid or member not in party.members():
            raise PartyError("not_member")
        now = self.clock()
        if block and len(party.blocked) < MAX_BLOCKED:
            party.blocked[member] = self.players[member].name
        self._vacate(party, member, now, "removed")
        self._fill_party(party, now)

    def _vacate(self, party, uuid, now, reason):
        party.handoff_id = secrets.token_urlsafe(9)
        party.invited_at = None
        party.accepted = set()
        for slot in party.slots:
            if slot["member"] == uuid:
                slot["member"], slot["joined"] = None, False
        player = self.players[uuid]
        player.party = None
        self._notice(player, "left_party", now, party=party.id, reason=reason)
        if party.full_since is not None:
            party.full_since = None
            for slot in party.slots:
                slot["joined"] = False
        if party.leader == uuid:
            others = [
                member for member in party.members() if self._present(self.players[member], now)
            ]
            if not others:
                self._close(party, now)
                return
            party.leader = self.rng.choice(sorted(others))
            self._notice(self.players[party.leader], "leader_now", now, party=party.id)
        self._touch_party(party)

    def _drop(self, party):
        del self.parties[party.id]
        self.floor_version[party.floor] += 1

    def _check_joined(self, party, now):
        """Legacy `joined` wire field means current game presence, not party membership."""
        changed = False
        for slot in party.slots:
            player = self.players[slot["member"]]
            present = player.in_game and player.mod_seen > now - PRESENCE_GRACE
            if slot["joined"] != present:
                slot["joined"] = present
                changed = True
        if changed:
            self._touch_party(party)

    def handoff(self, uuid):
        """Small mod view; no requirements, bans, stats or arbitrary commands."""
        player = self.players.get(uuid)
        party = self.parties.get(player.party) if player else None
        if not party:
            return None
        now = self.clock()
        return {
            "party_id": party.id,
            "handoff_id": party.handoff_id,
            "leader": self.players[party.leader].name,
            "you_lead": uuid == party.leader,
            "full": not party.open_roles(),
            "invited": party.invited_at is not None,
            "members": [
                {
                    "name": self.players[member].name,
                    "online": self.players[member].in_game
                    and self.players[member].mod_seen > now - PRESENCE_GRACE,
                    "accepted": member in party.accepted,
                }
                for member in party.members()
            ],
        }

    def report_roster(self, uuid, party_id, handoff_id, leader, names):
        party = self._led(uuid)
        if party.id != party_id or party.handoff_id != handoff_id:
            raise PartyError("stale_handoff")
        expected = {self.players[member].name.lower(): member for member in party.members()}
        actual = {name.lower() for name in names}
        if leader.lower() != self.players[uuid].name.lower() or not actual <= expected.keys():
            raise PartyError("game_party_conflict")
        if self.players[uuid].name.lower() not in actual:
            raise PartyError("invalid_roster")
        accepted = {expected[name] for name in actual}
        if party.accepted != accepted:
            party.accepted = accepted
            self._touch_party(party)
        if len(accepted) == 5:
            self.confirm_joined(uuid, party_id, accepted)
            return None
        return party

    def invite(self, uuid, party_id, handoff_id, leader, names, retry):
        party = self.report_roster(uuid, party_id, handoff_id, leader, names)
        if party is None:
            return []
        now = self.clock()
        view = self.handoff(uuid)
        if not view["full"] or not all(member["online"] for member in view["members"]):
            raise PartyError("not_ready")
        if party.invited_at is not None:
            if not retry:
                return []  # Lost responses / another running client cannot repeat the round.
            if now < party.invited_at + 10:
                raise PartyError("invite_cooldown")
        elif retry:
            raise PartyError("not_invited")
        party.invited_at = now
        self._touch_party(party)
        return [
            self.players[member].name for member in party.members() if member not in party.accepted
        ]

    def confirm_joined(self, uuid, party_id, members):
        """Finish only after the leader's mod reports the complete Hypixel roster."""
        party = self._led(uuid)
        if party.id != party_id or party.open_roles() or set(members) != set(party.members()):
            raise PartyError("roster_mismatch")
        now = self.clock()
        roster = [
            {"uuid": member, "name": self.players[member].name, "role": slot["role"]}
            for slot in party.slots
            if (member := slot["member"])
        ]
        for member in party.members():
            player = self.players[member]
            player.party = None
            self._notice(player, "party_joined", now, party=party.id, roster=roster)
        self._drop(party)

    # -- periodic sweep ------------------------------------------------------------

    def sweep(self):
        """Presence, join windows, bans and idle cleanup. Run every few seconds."""
        now = self.clock()
        refill = set()
        for player in list(self.players.values()):
            if player.banned_until and player.banned_until <= now:
                player.banned_until = 0
                self._touch(player)
            in_game = player.in_game and player.mod_seen > now - PRESENCE_GRACE
            if in_game != player.in_game:
                player.in_game = in_game
                self._touch(player)
            if not self._present(player, now):
                if player.looking:
                    self._stop_looking(player)
                    self._notice(player, "stopped_looking", now, reason="offline")
                party = self.parties.get(player.party)
                # Once full, the five-minute join window decides instead (with a ban).
                if party and (party.full_since is None or party.invited_at is not None):
                    self._vacate(party, player.uuid, now, "offline")
                    refill.add(party.id)
                elif (
                    not party
                    and not player.looking
                    and player.banned_until <= now
                    and max(player.web_seen, player.mod_seen) <= now - IDLE_FORGET
                ):
                    del self.players[player.uuid]
                    self.changed.discard(player.uuid)
        for party in list(self.parties.values()):
            if party.full_since is None:
                continue
            self._check_joined(party, now)
            if party.invited_at is None and now >= party.full_since + JOIN_WINDOW:
                # Collect first: vacating reopens the party and clears the joined flags.
                missing = [s["member"] for s in party.slots if not s["joined"]]
                for uuid in missing:
                    self.players[uuid].banned_until = now + NO_SHOW_BAN
                    if party.id in self.parties:
                        self._vacate(party, uuid, now, "no_show")
                    else:
                        self.players[uuid].party = None
                refill.add(party.id)
        for party_id in refill:
            if party := self.parties.get(party_id):
                self._fill_party(party, now)
        due = [
            party
            for party in self.parties.values()
            if party.full_since is None
            and party.counted_at <= now - COUNT_INTERVAL
            and self.players[party.leader].web_seen > now - PRESENCE_GRACE
        ]
        deadline = time.perf_counter() + COUNT_BUDGET
        for party in sorted(due, key=lambda party: party.counted_at):
            if time.perf_counter() > deadline:
                break
            party.counted_at = now
            counts = self._count(party)
            if counts != party.counts:
                party.counts = counts
                self._touch(self.players[party.leader])

    def _count(self, party):
        """One pass over this floor's lookers; the team limit is checked once per looker."""
        lookers = self.lookers[party.floor]
        average = self.team_s_plus(party)
        open_roles = set(party.open_roles())
        looking = dict.fromkeys(open_roles, 0)
        qualify = dict.fromkeys(open_roles, 0)
        for player in lookers.values():
            roles = [role for role in player.looking["classes"] if role in open_roles]
            if not roles:
                continue
            limit = player.looking["limit"]
            allowed = player.uuid not in party.blocked and (
                limit is None or (average is not None and average <= limit)
            )
            for role in roles:
                looking[role] += 1
                if allowed and qualifies(party.checks[role], player.stats):
                    qualify[role] += 1
        return {
            "looking": len(lookers),
            "roles": {
                role: {"looking": looking[role], "qualify": qualify[role]} for role in open_roles
            },
        }

    # -- views ---------------------------------------------------------------------

    def public_stats(self, player, role, floor):
        if player.stats is None:
            return None
        return {metric: stat(player.stats, metric, role, floor) for metric in METRICS}

    def listing(self, party):
        """Compact row, identical for every viewer; eligibility is computed by the client."""
        leader = self.players[party.leader]
        catacombs = [
            self.players[uuid].stats["catacombs"]
            for uuid in party.members()
            if self.players[uuid].stats and self.players[uuid].stats["catacombs"] is not None
        ]
        return {
            "id": party.id,
            "floor": party.floor,
            "leader": leader.name,
            "leader_uuid": leader.uuid,
            "created_at": party.created,
            "slots": [{"role": s["role"], "filled": bool(s["member"])} for s in party.slots],
            "rules": party.rules,
            "team": {
                "catacombs_avg": sum(catacombs) / len(catacombs) if catacombs else None,
                "s_plus_ms_avg": self.team_s_plus(party),
            },
        }

    def detail(self, party):
        """Listing plus member stats, loaded when a party is expanded."""
        members = []
        for index, slot in enumerate(party.slots):
            if slot["member"]:
                player = self.players[slot["member"]]
                members.append(
                    {
                        "slot": index,
                        "uuid": player.uuid,
                        "name": player.name,
                        "leader": slot["member"] == party.leader,
                        "stats": self.public_stats(player, slot["role"], party.floor),
                    }
                )
        return {**self.listing(party), "members": members}

    def visible(self, party, player):
        return not party.paused and player.uuid not in party.blocked

    def personal(self, uuid):
        now = self.clock()
        player = self._get(uuid)
        party = self.parties.get(player.party)
        view = None
        if party:
            view = {
                **self.detail(party),
                "paused": party.paused,
                "full_since": party.full_since,
                "join_deadline": party.full_since + JOIN_WINDOW
                if party.full_since is not None and party.invited_at is None
                else None,
                "joined": [s["joined"] for s in party.slots],
                "invited": party.invited_at is not None,
                "accepted": [s["member"] in party.accepted for s in party.slots],
                "you_lead": party.leader == uuid,
            }
            if party.leader == uuid:
                view["blocked"] = sorted(
                    ({"uuid": key, "name": name} for key, name in party.blocked.items()),
                    key=lambda entry: entry["name"].lower(),
                )
                view["matching"] = party.counts
        looking = player.looking
        return {
            "version": 1,
            "state_version": player.version,
            "state_id": player.state_id,
            "server_time": now,
            "you": {
                "uuid": player.uuid,
                "name": player.name,
                "in_game": player.in_game,
                "banned_until": player.banned_until if player.banned_until > now else None,
                "looking": {k: looking[k] for k in ("floor", "classes", "limit", "since")}
                if looking
                else None,
                # Matching inputs, so the client can show eligibility for any listing.
                "stats": player.stats,
            },
            "notices": list(player.notices),
            "party": view,
        }
