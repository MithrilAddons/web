"""Location game: the live pool of approved captures, solo runs and linked players' bests.

Runs live in memory, so a restart drops them. Which locations each player has seen and
linked players' solo bests sit in records.sqlite3, so account erasure removes them.
Each live location's six faces are packed into one WebP image, so a round costs one request.
"""

import io
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .location_world import build

ROUNDS = 5
TIMER = 25.0
GRACE = 1.0  # a guess this late still counts, to absorb lag
LOADING = 20.0  # a round starts by itself if the panorama never reports loaded
RUN_KEPT = 3600
MAX_RUNS = 5000
GUEST_SEEN_KEPT = 30 * 86400
FACE = 1024
# Picks and shuffles locations; the system source keeps the order unpredictable.
_random = secrets.SystemRandom()


class GameError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


@dataclass(frozen=True)
class Location:
    id: str
    island: str
    island_name: str
    x: float  # world blocks, offsets applied
    z: float
    captured_by: str | None


@dataclass
class Round:
    location: Location
    token: str
    issued: float
    started: float | None = None
    result: dict | None = None


@dataclass
class Run:
    id: str
    player: str
    uuid: str | None
    rounds: list[Round]
    created: float
    index: int = 0
    best: dict | None = field(default=None)


class LocationGame:
    def __init__(self, records, captures, folder: Path):
        self.records, self.captures, self.folder = records, captures, folder
        self.db, self.clock = records.db, records.clock
        self.world = None
        self.pool: dict[str, Location] = {}
        self.runs: dict[str, Run] = {}
        self.tokens: dict[str, tuple[str, int]] = {}
        self.lock = threading.Lock()

    # The pool

    def _atlas(self, location_id):
        return self.folder / f"{location_id}.webp"

    def _pack(self, location_id):
        """Faces in Minecraft's panorama order, three across and two down."""
        path = self._atlas(location_id)
        if path.is_file():
            return
        atlas = Image.new("RGB", (FACE * 3, FACE * 2))
        for face in range(6):
            with Image.open(self.captures.face_path(location_id, face)) as image:
                atlas.paste(
                    image.convert("RGB").resize((FACE, FACE), Image.Resampling.LANCZOS),
                    (face % 3 * FACE, face // 3 * FACE),
                )
        output = io.BytesIO()
        atlas.save(output, "WEBP", quality=88, method=4)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(output.getvalue())
        temporary.replace(path)

    def refresh(self):
        """Rebuilds the guessing map and the pool from what is approved now."""
        with self.records.lock:
            maps = self.db.execute(
                "SELECT * FROM capture_maps m WHERE status='approved' AND updated="
                "(SELECT MAX(updated) FROM capture_maps WHERE island=m.island "
                "AND status='approved')"
            ).fetchall()
            rows = self.db.execute(
                "SELECT id, island, island_name, x, z, name FROM capture_locations "
                "WHERE status='approved'"
            ).fetchall()
        entries = []
        for row in maps:
            path = self.captures.map_path(row["id"])
            if path.is_file():
                with Image.open(path) as image:
                    entries.append({**dict(row), "image": image.convert("RGBA")})
        world = build(entries)
        pool = {}
        for row in rows if world else ():
            if row["island"] not in world.islands:
                continue
            x, z = world.spot(row["island"], row["x"], row["z"])
            # A spot the map gives to another island could never be guessed right.
            if world.island_at(x, z) != row["island"]:
                continue
            try:
                self._pack(row["id"])
            except OSError:
                continue
            island = world.islands[row["island"]]
            pool[row["id"]] = Location(row["id"], row["island"], island.name, x, z, row["name"])
        live = set(pool)
        for path in self.folder.glob("*.webp"):
            if path.stem not in live:
                path.unlink(missing_ok=True)
        with self.lock:
            self.world, self.pool = world, pool

    # Runs

    def _choose(self, player):
        with self.records.lock:
            seen = dict(
                self.db.execute(
                    "SELECT location, seen FROM location_seen WHERE player=?", (player,)
                ).fetchall()
            )
        ids = list(self.pool)
        if len(ids) < ROUNDS:
            raise GameError(503, "Not enough locations yet. Check back soon.")
        _random.shuffle(ids)
        ids.sort(key=lambda location_id: seen.get(location_id, 0))
        chosen = ids[:ROUNDS]
        _random.shuffle(chosen)
        return [self.pool[location_id] for location_id in chosen]

    def _issue(self, run, index, now):
        token = secrets.token_urlsafe(18)
        run.rounds[index].token, run.rounds[index].issued = token, now
        self.tokens[token] = (run.id, index)

    def start(self, player, uuid):
        if not self.world:
            raise GameError(503, "The game is getting ready. Try again in a moment.")
        locations = self._choose(player)
        now = self.clock()
        run = Run(
            secrets.token_urlsafe(16),
            player,
            uuid,
            [Round(location, "", now) for location in locations],
            now,
        )
        with self.lock:
            # One run per player, and a bound on memory.
            for old in [r for r in self.runs.values() if r.player == player]:
                self._drop(old)
            while len(self.runs) >= MAX_RUNS:
                self._drop(next(iter(self.runs.values())))
            self.runs[run.id] = run
            self._issue(run, 0, now)
            return self._state(run, now)

    def _drop(self, run):
        self.runs.pop(run.id, None)
        for item in run.rounds:
            self.tokens.pop(item.token, None)

    def _run(self, run_id, player):
        run = self.runs.get(run_id)
        if not run or run.player != player:
            raise GameError(404, "This run has ended. Start a new one.")
        return run

    def _settle(self, run, now):
        """Starts a round whose panorama never reported loaded, and ends one that ran out."""
        current = run.rounds[run.index]
        if current.result:
            return
        if current.started is None and now >= current.issued + LOADING:
            current.started = current.issued + LOADING
        if current.started is not None and now > current.started + TIMER + GRACE:
            self._finish_round(run, current, None, now)

    def _finish_round(self, run, current, pin, now):
        location = current.location
        if pin is None:
            score, distance, guessed = 0, None, None
        else:
            score, distance, guessed = self.world.score(
                location.island, location.x, location.z, *pin
            )
        current.result = {
            "score": score,
            "distance": None if distance is None else round(distance, 1),
            "guessed": guessed,
            "pin": None if pin is None else list(pin),
            "answer": {
                "island": location.island,
                "name": location.island_name,
                "x": location.x,
                "z": location.z,
            },
            "captured_by": location.captured_by,
        }
        with self.records.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO location_seen VALUES (?, ?, ?)",
                (run.player, location.id, now),
            )
        if run.index == len(run.rounds) - 1 and run.uuid:
            run.best = self._record(run.uuid, sum(r.result["score"] for r in run.rounds), now)

    def _record(self, uuid, total, now):
        with self.records.lock, self.db:
            before = self.db.execute(
                "SELECT best FROM location_solo_best WHERE uuid=?", (uuid,)
            ).fetchone()
            self.db.execute(
                "INSERT INTO location_solo_best VALUES (?, ?, 1, ?, ?) ON CONFLICT(uuid) DO UPDATE "
                "SET best=MAX(best, excluded.best), runs=runs+1, points=points+excluded.points, "
                "updated=excluded.updated",
                (uuid, total, total, now),
            )
        return {**self.best(uuid), "new_best": before is None or total > before[0]}

    def best(self, uuid):
        with self.records.lock:
            row = self.db.execute(
                "SELECT best, runs, points FROM location_solo_best WHERE uuid=?", (uuid,)
            ).fetchone()
        if not row:
            return {"best": None, "runs": 0, "average": None}
        return {
            "best": row["best"],
            "runs": row["runs"],
            "average": round(row["points"] / row["runs"]),
        }

    def _state(self, run, now):
        self._settle(run, now)
        current = run.rounds[run.index]
        finished = run.index == len(run.rounds) - 1 and current.result is not None
        if finished:
            phase = "finished"
        elif current.result:
            phase = "revealed"
        else:
            phase = "playing" if current.started is not None else "loading"
        results = [item.result for item in run.rounds if item.result]
        state = {
            "version": 1,
            "id": run.id,
            "round": run.index + 1,
            "rounds": len(run.rounds),
            "timer": TIMER,
            "state": phase,
            "now": now,
            "results": results,
            "total": sum(result["score"] for result in results),
        }
        if phase in ("loading", "playing"):
            state["panorama"] = f"/api/v1/games/locations/panorama/{current.token}.webp"
        if phase == "playing":
            state["deadline"] = current.started + TIMER
        if finished and run.best:
            state["best"] = run.best
        return state

    def state(self, run_id, player):
        with self.lock:
            return self._state(self._run(run_id, player), self.clock())

    def _current(self, run, number):
        if number != run.index + 1:
            raise GameError(409, "That round is over")
        return run.rounds[run.index]

    def ready(self, run_id, player, number):
        with self.lock:
            run, now = self._run(run_id, player), self.clock()
            current = self._current(run, number)
            if current.started is None and not current.result:
                current.started = now
            return self._state(run, now)

    def guess(self, run_id, player, number, x, z):
        with self.lock:
            run, now = self._run(run_id, player), self.clock()
            self._settle(run, now)
            current = self._current(run, number)
            if current.result:
                raise GameError(409, "Time's up for this round")
            if current.started is None:
                raise GameError(409, "The round hasn't started yet")
            self._finish_round(run, current, (x, z), now)
            return self._state(run, now)

    def next(self, run_id, player, number):
        with self.lock:
            run, now = self._run(run_id, player), self.clock()
            self._settle(run, now)
            current = self._current(run, number)
            if not current.result:
                raise GameError(409, "Finish this round first")
            if run.index == len(run.rounds) - 1:
                raise GameError(409, "This run is over")
            run.index += 1
            self._issue(run, run.index, now)
            return self._state(run, now)

    def panorama(self, token):
        with self.lock:
            found = self.tokens.get(token)
            run = self.runs.get(found[0]) if found else None
            if not run or run.index != found[1]:
                raise GameError(404, "Unknown panorama")
            location_id = run.rounds[found[1]].location.id
        path = self._atlas(location_id)
        if not path.is_file():
            raise GameError(404, "Unknown panorama")
        return path.read_bytes()

    def cleanup(self):
        now = self.clock()
        with self.lock:
            for run in [r for r in self.runs.values() if r.created < now - RUN_KEPT]:
                self._drop(run)
        with self.records.lock, self.db:
            self.db.execute(
                "DELETE FROM location_seen WHERE player LIKE 'g:%' AND seen<?",
                (now - GUEST_SEEN_KEPT,),
            )
