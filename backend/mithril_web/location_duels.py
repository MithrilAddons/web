"""Location game duels: two players, the same panoramas, and health that the worse guess loses.

Everything here runs on the server's event loop: routes are async and call these methods
directly, and a background task calls advance() a few times a second to move clocks along.
Live duels, challenges and invites live in memory, so a restart cancels them without any rating
change. Finished duels with a linked player, and ratings, sit in records.sqlite3.
"""

import asyncio
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from . import glicko
from .location_game import GameError

HEALTH = 6000
TIMER = 25.0
CUT = 10.0  # the first guess leaves the other player this long at most
REVEAL = 8.0
COUNTDOWN = 3.0
LOADING = 20.0  # a round starts anyway if a panorama never reports loaded
GRACE = 1.0
MAX_ROUNDS = 15
MIN_ROUNDS = 5
RECONNECT = 30.0
CHALLENGE_KEPT = 120.0
INVITE_KEPT = 600.0
ONLINE = 60.0
RATED_PER_PAIR = 3
PROVISIONAL_RD = 110.0
WEEK = 7 * 86400
MAX_DUELS = 2000
MAX_PENDING = 5000
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def multiplier(number):
    """Damage grows so long duels end: ×1 for rounds 1-3, ×1.5 in round 4, then +0.5 a round."""
    if number <= 3:
        return 1.0
    return 1.5 + 0.5 * (number - 4)


TALLY = {"win": "wins", "loss": "losses", "draw": "draws"}


def outcome(winner, index):
    """win, loss or draw from one seat's side."""
    if winner is None:
        return "draw"
    return "win" if winner == index else "loss"


def season_of(moment):
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m")


def months_between(earlier, later):
    year_a, month_a = (int(part) for part in earlier.split("-"))
    year_b, month_b = (int(part) for part in later.split("-"))
    return (year_b - year_a) * 12 + month_b - month_a


@dataclass
class Seat:
    who: dict
    seen: float
    health: float = HEALTH
    waiting: int = 0
    loaded: bool = False
    guess: dict | None = None


@dataclass
class DuelRound:
    location: object
    token: str
    issued: float
    started: float | None = None
    deadline: float | None = None
    result: dict | None = None


@dataclass
class Duel:
    id: str
    seats: list[Seat]
    locations: list
    created: float
    rounds: list[DuelRound] = field(default_factory=list)
    countdown: float | None = None
    revealed: float | None = None
    finished: dict | None = None
    version: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def seat(self, player):
        for index, seat in enumerate(self.seats):
            if seat.who["player"] == player:
                return index, seat
        raise GameError(404, "This duel isn't yours")


@dataclass
class Pending:
    """A challenge to one player, or an invite code anyone with the link can use."""

    id: str
    sender: dict
    created: float
    expires: float
    target: str | None = None
    target_name: str | None = None


class LocationDuels:
    def __init__(self, game, records, wait=25.0):
        self.game, self.records, self.wait = game, records, wait
        self.db, self.clock = records.db, records.clock
        self.duels: dict[str, Duel] = {}
        self.pending: dict[str, Pending] = {}
        self.tokens: dict[str, tuple[str, int]] = {}
        self.presence: dict[str, dict] = {}  # player -> who, seen, waiting, event

    # Presence and the inbox

    def _player(self, who):
        entry = self.presence.setdefault(
            who["player"],
            {"who": who, "seen": 0.0, "waiting": 0, "version": 0, "event": asyncio.Event()},
        )
        entry["who"], entry["seen"] = who, self.clock()
        return entry

    def _poke(self, player):
        entry = self.presence.get(player)
        if entry:
            entry["version"] += 1
            old, entry["event"] = entry["event"], asyncio.Event()
            old.set()

    def _active(self, player):
        for duel in self.duels.values():
            if not duel.finished and any(seat.who["player"] == player for seat in duel.seats):
                return duel
        return None

    def inbox(self, who):
        now = self.clock()
        self._player(who)
        player = who["player"]
        active = self._active(player)
        incoming, outgoing = [], []
        for item in self.pending.values():
            if item.expires <= now:
                continue
            if item.target == player:
                incoming.append(
                    {"id": item.id, "from": item.sender["name"], "expires": item.expires}
                )
            elif item.sender["player"] == player:
                kind = "invite" if item.target is None else "challenge"
                outgoing.append(
                    {"id": item.id, "kind": kind, "to": item.target_name, "expires": item.expires}
                )
        return {
            "version": 1,
            "revision": self.presence[player]["version"],
            "now": now,
            "you": who["name"],
            "duel": active.id if active else None,
            "incoming": incoming,
            "outgoing": outgoing,
        }

    async def wait_inbox(self, who, after):
        """The inbox once its revision passes `after`, or as it stands after the wait."""
        entry = self._player(who)
        if after < entry["version"]:
            return self.inbox(who)
        event = entry["event"]
        entry["waiting"] += 1
        try:
            await asyncio.wait_for(event.wait(), self.wait)
        except TimeoutError:
            pass
        finally:
            entry["waiting"] -= 1
            entry["seen"] = self.clock()
        return self.inbox(who)

    def _online(self, name):
        now = self.clock()
        for entry in self.presence.values():
            if entry["who"]["name"].lower() == name.lower() and (
                entry["waiting"] or now - entry["seen"] <= ONLINE
            ):
                return entry["who"]
        return None

    # Challenges and invites

    def _check_free(self, player):
        if self._active(player):
            raise GameError(409, "Finish your current duel first")

    def _bound(self):
        now = self.clock()
        for key in [key for key, item in self.pending.items() if item.expires <= now]:
            del self.pending[key]
        if len(self.pending) >= MAX_PENDING:
            raise GameError(503, "Too many open challenges right now. Try again soon.")

    def challenge(self, who, name=None, target=None):
        """Challenges a player by name (if they have the game open) or a known opponent."""
        self._player(who)
        self._check_free(who["player"])
        self._bound()
        if target is None:
            found = self._online(name)
            if not found:
                raise GameError(404, f"{name} doesn't have the game open right now")
            target = found
        if target["player"] == who["player"]:
            raise GameError(422, "You can't challenge yourself")
        self._withdraw(who["player"], challenges=True)
        now = self.clock()
        item = Pending(
            secrets.token_urlsafe(9),
            who,
            now,
            now + CHALLENGE_KEPT,
            target["player"],
            target["name"],
        )
        self.pending[item.id] = item
        self._poke(target["player"])
        self._poke(who["player"])
        return {"version": 1, "id": item.id, "expires": item.expires}

    def _withdraw(self, player, challenges):
        """Drops the player's earlier challenge (or invite): one of each at a time."""
        stale = [
            key
            for key, item in self.pending.items()
            if item.sender["player"] == player and (item.target is not None) == challenges
        ]
        for key in stale:
            del self.pending[key]

    def invite(self, who):
        self._player(who)
        self._check_free(who["player"])
        self._bound()
        self._withdraw(who["player"], challenges=False)
        now = self.clock()
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        item = Pending(code, who, now, now + INVITE_KEPT)
        self.pending[code] = item
        self._poke(who["player"])
        return {"version": 1, "code": code, "expires": item.expires}

    def _take(self, key, who, kind):
        item = self.pending.get(key)
        if not item or item.expires <= self.clock() or (item.target is None) != (kind == "invite"):
            raise GameError(
                404, "This invite has expired" if kind == "invite" else "This challenge has expired"
            )
        if kind == "challenge" and item.target != who["player"]:
            raise GameError(404, "This challenge has expired")
        if item.sender["player"] == who["player"]:
            raise GameError(422, "You can't duel yourself")
        return item

    def accept(self, challenge_id, who):
        item = self._take(challenge_id, who, "challenge")
        return self._start(item, who)

    def join(self, code, who):
        item = self._take(code.upper(), who, "invite")
        return self._start(item, who)

    def decline(self, challenge_id, who):
        item = self.pending.get(challenge_id)
        if item and who["player"] in (item.target, item.sender["player"]):
            del self.pending[challenge_id]
            self._poke(item.sender["player"])
            if item.target:
                self._poke(item.target)
        return {"version": 1}

    def _start(self, item, who):
        self._player(who)
        self._check_free(who["player"])
        self._check_free(item.sender["player"])
        if not self.game.world:
            raise GameError(503, "The game is getting ready. Try again in a moment.")
        players = [item.sender, who]
        locations = self.game.pick([seat["player"] for seat in players], MAX_ROUNDS)
        if len(locations) < MIN_ROUNDS:
            raise GameError(503, "Not enough locations yet. Check back soon.")
        del self.pending[item.id]
        now = self.clock()
        while len(self.duels) >= MAX_DUELS:
            self._forget(next(iter(self.duels.values())))
        duel = Duel(
            secrets.token_urlsafe(16),
            [Seat(player, now) for player in players],
            locations,
            now,
        )
        self.duels[duel.id] = duel
        self._issue(duel, now)
        for seat in duel.seats:
            self._poke(seat.who["player"])
        return {"version": 1, "duel": duel.id}

    def _forget(self, duel):
        self.duels.pop(duel.id, None)
        for item in duel.rounds:
            self.tokens.pop(item.token, None)

    # Rounds

    def _issue(self, duel, now):
        token = secrets.token_urlsafe(18)
        duel.rounds.append(DuelRound(duel.locations[len(duel.rounds)], token, now))
        self.tokens[token] = (duel.id, len(duel.rounds) - 1)
        duel.revealed = None
        for seat in duel.seats:
            seat.loaded, seat.guess = False, None

    def _bump(self, duel):
        duel.version += 1
        old, duel.changed = duel.changed, asyncio.Event()
        old.set()

    def panorama(self, token):
        found = self.tokens.get(token)
        duel = self.duels.get(found[0]) if found else None
        if not duel or len(duel.rounds) - 1 != found[1]:
            raise GameError(404, "Unknown panorama")
        return self.game.atlas(duel.rounds[found[1]].location.id)

    def _begin(self, current, at):
        current.started = at
        current.deadline = at + TIMER

    def _maybe_begin(self, duel, now):
        current = duel.rounds[-1]
        if current.started is not None or current.result:
            return False
        ready = all(seat.loaded for seat in duel.seats) or now >= current.issued + LOADING
        if not ready:
            return False
        if len(duel.rounds) == 1:
            # The first round counts down once both have it on screen.
            if duel.countdown is None:
                duel.countdown = now + COUNTDOWN
                return True
            if now < duel.countdown:
                return False
            self._begin(current, duel.countdown)
        else:
            self._begin(current, now)
        return True

    def ready(self, duel_id, who, number):
        duel, (_, seat) = self._mine(duel_id, who)
        self._current(duel, number)
        seat.loaded = True
        self._maybe_begin(duel, self.clock())
        self._bump(duel)
        return self.view(duel, who)

    def guess(self, duel_id, who, number, x, z):
        duel, (_, seat) = self._mine(duel_id, who)
        now = self.clock()
        self.advance(now)
        current = self._current(duel, number)
        if current.result or current.started is None or now < current.started:
            raise GameError(409, "This round isn't open for guesses")
        if now > current.deadline + GRACE:
            raise GameError(409, "Time's up for this round")
        if seat.guess:
            raise GameError(409, "You've already guessed")
        seat.guess = {"pin": [x, z], "at": now}
        current.deadline = min(current.deadline, now + CUT)
        if all(other.guess for other in duel.seats):
            self._resolve(duel, now)
        self._bump(duel)
        return self.view(duel, who)

    def _resolve(self, duel, now):
        current, number = duel.rounds[-1], len(duel.rounds)
        location = current.location
        scores = []
        for seat in duel.seats:
            if seat.guess:
                points, distance, guessed = self.game.world.score(
                    location.island, location.x, location.z, *seat.guess["pin"]
                )
            else:
                points, distance, guessed = 0, None, None
            scores.append({"score": points, "distance": distance, "guessed": guessed})
        loser = 0 if scores[0]["score"] < scores[1]["score"] else 1
        damage = abs(scores[0]["score"] - scores[1]["score"]) * multiplier(number)
        duel.seats[loser].health = max(0.0, duel.seats[loser].health - damage)
        current.result = {
            "round": number,
            "multiplier": multiplier(number),
            "damage": round(damage) if damage else 0,
            "loser": loser if damage else None,
            "answer": {
                "island": location.island,
                "name": location.island_name,
                "x": location.x,
                "z": location.z,
            },
            "captured_by": location.captured_by,
            "seats": [
                {
                    **score,
                    "distance": None if score["distance"] is None else round(score["distance"], 1),
                    "pin": seat.guess["pin"] if seat.guess else None,
                    "health": round(seat.health),
                }
                for seat, score in zip(duel.seats, scores, strict=True)
            ],
        }
        for seat in duel.seats:
            self.game.mark_seen(seat.who["player"], location.id, now)
        duel.revealed = now
        if any(seat.health <= 0 for seat in duel.seats):
            self._finish(duel, 1 - loser, "health", now)
        elif number >= len(duel.locations):
            healths = [seat.health for seat in duel.seats]
            winner = None if healths[0] == healths[1] else healths.index(max(healths))
            self._finish(duel, winner, "rounds", now)

    def _connected(self, seat, now):
        return seat.waiting > 0 or now - seat.seen <= RECONNECT

    def advance(self, now=None):
        """Moves every live duel's clocks along; called a few times a second."""
        now = self.clock() if now is None else now
        done = [
            duel
            for duel in self.duels.values()
            if duel.finished and now - duel.finished["at"] > RECONNECT * 4
        ]
        for duel in done:
            self._forget(duel)
        for duel in self.duels.values():
            if not duel.finished and self._step(duel, now):
                self._bump(duel)

    def _step(self, duel, now):
        gone = [index for index, seat in enumerate(duel.seats) if not self._connected(seat, now)]
        if len(gone) == 2:
            self._finish(duel, None, "cancelled", now)
            return True
        if gone:
            self._finish(duel, 1 - gone[0], "forfeit", now)
            return True
        current = duel.rounds[-1]
        if current.result:
            if now >= duel.revealed + REVEAL:
                self._issue(duel, now)
                return True
            return False
        if self._maybe_begin(duel, now):
            return True
        if current.deadline is not None and now > current.deadline + GRACE:
            self._resolve(duel, now)
            return True
        return False

    def leave(self, duel_id, who):
        duel, (index, _) = self._mine(duel_id, who)
        if not duel.finished:
            self._finish(duel, 1 - index, "forfeit", self.clock())
            self._bump(duel)
        return {"version": 1}

    def rematch(self, duel_id, who):
        duel, (index, _) = self._mine(duel_id, who)
        if not duel.finished:
            raise GameError(409, "This duel is still going")
        return self.challenge(who, target=duel.seats[1 - index].who)

    def _mine(self, duel_id, who):
        duel = self.duels.get(duel_id)
        if not duel:
            raise GameError(404, "This duel has ended")
        found = duel.seat(who["player"])
        found[1].seen = self.clock()
        return duel, found

    def _current(self, duel, number):
        if duel.finished or number != len(duel.rounds):
            raise GameError(409, "That round is over")
        return duel.rounds[-1]

    # Finishing and ratings

    def _finish(self, duel, winner, reason, now):
        duel.finished = {"winner": winner, "reason": reason, "at": now, "ratings": None}
        for seat in duel.seats:
            self._poke(seat.who["player"])
        if reason == "cancelled":
            return
        linked = [seat.who["uuid"] for seat in duel.seats]
        if not any(linked):
            return
        rated = all(linked) and self._rated_today(*linked, now) < RATED_PER_PAIR
        if rated:
            duel.finished["ratings"] = self._rate(duel, winner, now)
        self._store(duel, winner, reason, rated, now)

    def _rated_today(self, a, b, now):
        start = datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.records.lock:
            return self.db.execute(
                "SELECT COUNT(*) FROM location_duels WHERE rated=1 AND finished>=? AND "
                "((a_uuid=? AND b_uuid=?) OR (a_uuid=? AND b_uuid=?))",
                (start.timestamp(), a, b, b, a),
            ).fetchone()[0]

    def _load(self, uuid, now):
        """A player's rating as of now: softened for each month missed, less certain when idle."""
        season = season_of(now)
        row = self.db.execute("SELECT * FROM location_ratings WHERE uuid=?", (uuid,)).fetchone()
        if not row:
            return {"rating": glicko.Strength(), "wins": 0, "losses": 0, "draws": 0, "peak": None}
        rating = glicko.Strength(row["rating"], row["rd"], row["volatility"])
        stats = {key: row[key] for key in ("wins", "losses", "draws", "peak")}
        if row["season"] != season:
            for _ in range(max(0, months_between(row["season"], season))):
                rating = glicko.soften(rating)
            stats = {"wins": 0, "losses": 0, "draws": 0, "peak": None}
        rating = glicko.idle(rating, (now - row["played"]) / WEEK)
        return {"rating": rating, **stats}

    def _rate(self, duel, winner, now):
        with self.records.lock, self.db:
            self._snapshot(season_of(now))
            players = [self._load(seat.who["uuid"], now) for seat in duel.seats]
            changes = []
            for index, seat in enumerate(duel.seats):
                me, them = players[index], players[1 - index]
                score = 0.5 if winner is None else float(winner == index)
                after = glicko.update(me["rating"], [(them["rating"], score)])
                me[TALLY[outcome(winner, index)]] += 1
                peak = max(me["peak"] or after.rating, after.rating)
                self.db.execute(
                    "INSERT OR REPLACE INTO location_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        seat.who["uuid"],
                        seat.who["name"],
                        after.rating,
                        after.rd,
                        after.volatility,
                        season_of(now),
                        me["wins"],
                        me["losses"],
                        me["draws"],
                        peak,
                        now,
                    ),
                )
                changes.append(
                    {
                        "before": round(me["rating"].rating),
                        "after": round(after.rating),
                        "provisional": after.rd >= PROVISIONAL_RD,
                    }
                )
        return changes

    def _snapshot(self, season):
        """Keeps the final top 10 of a finished season, before anyone's row moves on."""
        previous = (datetime.strptime(season + "-01", "%Y-%m-%d") - timedelta(days=1)).strftime(
            "%Y-%m"
        )
        if self.db.execute(
            "SELECT 1 FROM location_season_tops WHERE season=? LIMIT 1", (previous,)
        ).fetchone():
            return
        rows = self.db.execute(
            "SELECT uuid, name, rating FROM location_ratings WHERE season=? AND rd<? "
            "ORDER BY rating DESC LIMIT 10",
            (previous, PROVISIONAL_RD),
        ).fetchall()
        for rank, row in enumerate(rows, 1):
            self.db.execute(
                "INSERT INTO location_season_tops VALUES (?,?,?,?,?)",
                (previous, rank, row["uuid"], row["name"], round(row["rating"])),
            )

    def _store(self, duel, winner, reason, rated, now):
        ratings = duel.finished["ratings"] or [None, None]
        a, b = duel.seats
        with self.records.lock, self.db:
            self.db.execute(
                "INSERT INTO location_duels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    duel.id,
                    now,
                    a.who["uuid"],
                    a.who["name"],
                    b.who["uuid"],
                    b.who["name"],
                    winner,
                    reason,
                    int(rated),
                    json.dumps(ratings),
                    json.dumps([item.result for item in duel.rounds if item.result]),
                    round(a.health),
                    round(b.health),
                ),
            )

    # Views

    def view(self, duel, who):
        index, _ = duel.seat(who["player"])
        me, them = duel.seats[index], duel.seats[1 - index]
        now = self.clock()
        current = duel.rounds[-1]
        phase = self._phase(duel, now)
        results = [self._side(item.result, index) for item in duel.rounds if item.result]
        state = {
            "version": duel.version,
            "id": duel.id,
            "state": phase,
            "now": now,
            "round": len(duel.rounds),
            "rounds": len(duel.locations),
            "timer": TIMER,
            "health": HEALTH,
            "me": {"name": me.who["name"], "health": round(me.health), "guessed": bool(me.guess)},
            "opponent": {
                "name": them.who["name"],
                "health": round(them.health),
                "guessed": bool(them.guess),
                "connected": self._connected(them, now),
                "guest": them.who["uuid"] is None,
            },
            "results": results,
            "multiplier": multiplier(len(duel.rounds)),
        }
        if phase in ("loading", "playing"):
            state["panorama"] = f"/api/v1/games/locations/panorama/{current.token}.webp"
        if phase == "loading" and duel.countdown:
            state["countdown"] = duel.countdown
        if phase == "playing":
            state["deadline"] = current.deadline
        if phase == "revealed":
            state["next"] = duel.revealed + REVEAL
        if duel.finished:
            winner = duel.finished["winner"]
            ratings = duel.finished["ratings"]
            state["finished"] = {
                "result": outcome(winner, index),
                "reason": duel.finished["reason"],
                "rating": ratings[index] if ratings else None,
            }
        return state

    @staticmethod
    def _phase(duel, now):
        current = duel.rounds[-1]
        if duel.finished:
            return "finished"
        if current.result:
            return "revealed"
        if current.started is not None and now >= current.started:
            return "playing"
        return "loading"

    @staticmethod
    def _side(result, index):
        """A round's result from one player's side: theirs first."""
        mine, theirs = result["seats"][index], result["seats"][1 - index]
        return {
            "round": result["round"],
            "multiplier": result["multiplier"],
            "damage": result["damage"],
            "lost": None if result["loser"] is None else result["loser"] == index,
            "answer": result["answer"],
            "captured_by": result["captured_by"],
            "me": mine,
            "opponent": theirs,
        }

    def state(self, duel_id, who):
        duel, _ = self._mine(duel_id, who)
        return self.view(duel, who)

    async def wait_state(self, duel_id, who, after):
        duel, (_, seat) = self._mine(duel_id, who)
        if after < duel.version:
            return self.view(duel, who)
        event = duel.changed
        seat.waiting += 1
        try:
            await asyncio.wait_for(event.wait(), self.wait)
        except TimeoutError:
            pass
        finally:
            seat.waiting -= 1
            seat.seen = self.clock()
        return self.view(duel, who)

    # Ratings and history for the website

    def standing(self, uuid):
        with self.records.lock:
            row = self.db.execute("SELECT * FROM location_ratings WHERE uuid=?", (uuid,)).fetchone()
            if not row:
                return None
            now = self.clock()
            loaded = self._load(uuid, now)
        rating = loaded["rating"]
        return {
            "rating": round(rating.rating),
            "provisional": rating.rd >= PROVISIONAL_RD,
            "wins": loaded["wins"],
            "losses": loaded["losses"],
            "draws": loaded["draws"],
            "peak": round(loaded["peak"]) if loaded["peak"] else None,
        }

    def leaderboard(self, uuid):
        season = season_of(self.clock())
        with self.records.lock:
            rows = self.db.execute(
                "SELECT * FROM location_ratings WHERE season=? AND rd<? ORDER BY rating DESC",
                (season, PROVISIONAL_RD),
            ).fetchall()
            past = self.db.execute(
                "SELECT * FROM location_season_tops ORDER BY season DESC, rank LIMIT 60"
            ).fetchall()

        def entry(rank, row):
            return {
                "rank": rank,
                "name": row["name"],
                "rating": round(row["rating"]),
                "wins": row["wins"],
                "losses": row["losses"],
                "draws": row["draws"],
                "peak": round(row["peak"]),
                "you": row["uuid"] == uuid,
            }

        ranked = [entry(rank, row) for rank, row in enumerate(rows, 1)]
        mine = next((item for item in ranked if item["you"]), None)
        seasons = {}
        for row in past:
            seasons.setdefault(row["season"], []).append(
                {"rank": row["rank"], "name": row["name"], "rating": row["rating"]}
            )
        return {
            "version": 1,
            "season": season,
            "players": len(ranked),
            "top": ranked[:10],
            "you": mine if mine and mine["rank"] > 10 else None,
            "past": [{"season": key, "top": value} for key, value in seasons.items()],
        }

    def history(self, uuid, offset):
        with self.records.lock:
            rows = self.db.execute(
                "SELECT * FROM location_duels WHERE a_uuid=? OR b_uuid=? "
                "ORDER BY finished DESC LIMIT 20 OFFSET ?",
                (uuid, uuid, offset),
            ).fetchall()
            total = self.db.execute(
                "SELECT COUNT(*) FROM location_duels WHERE a_uuid=? OR b_uuid=?", (uuid, uuid)
            ).fetchone()[0]
        duels = []
        for row in rows:
            index = 0 if row["a_uuid"] == uuid else 1
            winner = row["winner"]
            ratings = json.loads(row["ratings"])
            duels.append(
                {
                    "id": row["id"],
                    "finished": row["finished"],
                    "opponent": row["b_name"] if index == 0 else row["a_name"],
                    "result": outcome(winner, index),
                    "reason": row["reason"],
                    "rated": bool(row["rated"]),
                    "rating": ratings[index],
                    "health": [row["a_health"], row["b_health"]][index],
                    "rounds": [self._side(result, index) for result in json.loads(row["rounds"])],
                }
            )
        return {"version": 1, "total": total, "duels": duels}

    def cleanup(self):
        now = self.clock()
        for key in [key for key, item in self.pending.items() if item.expires <= now]:
            del self.pending[key]
        for player in [
            key
            for key, entry in self.presence.items()
            if not entry["waiting"] and now - entry["seen"] > ONLINE * 10
        ]:
            del self.presence[player]
