"""Curator rounds: one game per account per UTC day, judged only on the backend.

Results live in records.sqlite3 so account erasure removes them with the PBs.
"""

import json
from datetime import UTC, datetime, timedelta

from .curator import compare
from .curator_data import date_of, day

GUESSES = 10


class GameError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


def points(guesses, solved):
    return GUESSES + 1 - guesses if solved else 0


def round_state(solved, finished):
    if solved:
        return "solved"
    return "failed" if finished else "playing"


def streaks(days):
    """Current and best runs of consecutive solved days, from sorted solved days."""
    best = run = 0
    previous = None
    for date in days:
        current = date_of(date)
        run = run + 1 if previous and current - previous == timedelta(days=1) else 1
        best, previous = max(best, run), current
    return run, best


class CuratorGame:
    def __init__(self, data, records):
        self.data, self.records = data, records

    def today(self):
        return day(self.data.clock())

    def resets_at(self):
        now = datetime.fromtimestamp(self.data.clock(), UTC)
        return int(
            (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(1)).timestamp()
        )

    def _result(self, date, uuid):
        row = self.records.db.execute(
            "SELECT guesses, solved, finished FROM curator_results WHERE day=? AND uuid=?",
            (date, uuid),
        ).fetchone()
        if not row:
            return [], False, False
        return json.loads(row["guesses"]), bool(row["solved"]), row["finished"] is not None

    def state(self, uuid):
        today = self.today()
        answer = self.data.locked(today)
        if not answer:
            return {"version": 1, "day": today, "state": "preparing", "resets_at": self.resets_at()}
        with self.records.lock:
            guesses, solved, finished = self._result(today, uuid)
        result = {
            "version": 1,
            "day": today,
            "number": answer["number"],
            "state": round_state(solved, finished),
            "limit": GUESSES,
            "resets_at": self.resets_at(),
            "guesses": guesses,
        }
        if finished:
            result["answer"] = {key: answer[key] for key in ("item", "name", "values", "icon")}
            result["stats"] = self.player_stats(uuid)
        return result

    def guess(self, uuid, name, date, item):
        today = self.today()
        answer = self.data.locked(today)
        if not answer:
            raise GameError(409, "Today's item is still being prepared")
        if date != today:
            raise GameError(409, "A new item is ready")
        guessed = self.data.guessable(item, today)
        if not guessed:
            raise GameError(404, "Unknown item")
        feedback = compare(
            guessed["values"],
            answer["values"],
            guessed["values"]["market"],
            answer["values"]["market"],
        )
        entry = {
            "item": item,
            "name": guessed["name"],
            "values": guessed["values"],
            "feedback": feedback,
            # An upgrade of the answer, or the item it upgrades from.
            "family": bool(answer["family"])
            and guessed["family"] == answer["family"]
            and item != answer["item"],
        }
        with self.records.lock, self.records.db:
            guesses, _, finished = self._result(today, uuid)
            if finished:
                raise GameError(409, "Today's round is already over")
            if any(previous["item"] == item for previous in guesses):
                raise GameError(409, "Already guessed")
            guesses.append(entry)
            solved = item == answer["item"]
            done = solved or len(guesses) >= GUESSES
            self.records.db.execute(
                """INSERT INTO curator_results VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(day, uuid) DO UPDATE SET name=excluded.name,
                guesses=excluded.guesses, solved=excluded.solved, finished=excluded.finished""",
                (
                    today,
                    uuid,
                    name,
                    json.dumps(guesses, sort_keys=True),
                    int(solved),
                    self.data.clock() if done else None,
                ),
            )
        return self.state(uuid)

    def _finished(self, uuid, season=""):
        return self.records.db.execute(
            "SELECT day, solved, json_array_length(guesses) AS used FROM curator_results "
            "WHERE uuid=? AND finished IS NOT NULL AND day LIKE ? ORDER BY day",
            (uuid, season + "%"),
        ).fetchall()

    def _streak(self, uuid):
        solved = [row["day"] for row in self._finished(uuid) if row["solved"]]
        current, best = streaks(solved)
        # A streak survives until a full day is missed.
        if not solved or date_of(self.today()) - date_of(solved[-1]) > timedelta(days=1):
            current = 0
        return current, best

    def player_stats(self, uuid):
        with self.records.lock:
            rows = self._finished(uuid)
            current, best = self._streak(uuid)
        solved = sum(row["solved"] for row in rows)
        return {
            "played": len(rows),
            "solved": solved,
            "streak": current,
            "best_streak": best,
        }

    def leaderboard(self, uuid):
        today = self.today()
        season = today[:7]
        with self.records.lock:
            rows = self.records.db.execute(
                """WITH season AS (
                    SELECT uuid, solved, json_array_length(guesses) AS used, day, name
                    FROM curator_results r WHERE day LIKE ? AND finished IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM sanctions s WHERE s.uuid=r.uuid
                        AND s.kind IN ('ban','network_ban') AND s.revoked IS NULL
                        AND (s.expires IS NULL OR s.expires>?))
                ), totals AS (
                    SELECT uuid,
                        SUM(CASE WHEN solved THEN ? - used ELSE 0 END) AS points,
                        SUM(solved) AS solved, COUNT(*) AS played, SUM(used) AS used,
                        (SELECT name FROM season l WHERE l.uuid=s.uuid
                            ORDER BY day DESC LIMIT 1) AS name
                    FROM season s GROUP BY uuid
                ) SELECT *, ROW_NUMBER() OVER (ORDER BY points DESC, used, uuid) AS rank
                FROM totals ORDER BY rank""",
                (season + "%", self.data.clock(), GUESSES + 1),
            ).fetchall()

            def entry(row):
                return {
                    "rank": row["rank"],
                    "name": row["name"],
                    "points": row["points"],
                    "solved": row["solved"],
                    "played": row["played"],
                    "streak": self._streak(row["uuid"])[0],
                    "you": row["uuid"] == uuid,
                }

            top = [entry(row) for row in rows[:10]]
            mine = next((row for row in rows if row["uuid"] == uuid), None)
            games = self._finished(uuid, season)
            current, best = self._streak(uuid)
        solves = [row["used"] for row in games if row["solved"]]
        first = date_of(season + "-01")
        following = (first + timedelta(days=32)).replace(day=1)
        return {
            "version": 1,
            "season": season,
            "day": date_of(today).day,
            "days": (following - first).days,
            "players": len(rows),
            "top": top,
            "you": entry(mine) if mine and mine["rank"] > 10 else None,
            "stats": {
                "points": sum(points(used, True) for used in solves),
                "rank": mine["rank"] if mine else None,
                "played": len(games),
                "solved": len(solves),
                "average": round(sum(solves) / len(solves), 1) if solves else None,
                "histogram": [solves.count(n) for n in range(1, GUESSES + 1)],
                "failed": len(games) - len(solves),
                "streak": current,
                "best_streak": best,
            },
        }
