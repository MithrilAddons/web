"""Submission history and bounded live evidence. Network calls never hold the DB lock."""

import json
import secrets
import sqlite3
import threading
import time

from fastapi import HTTPException

DAY = 86400


class RecordStore:
    def __init__(self, path, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS record_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pb_records (
                id TEXT PRIMARY KEY, uuid TEXT NOT NULL, floor TEXT NOT NULL, kind TEXT NOT NULL,
                real_ms INTEGER NOT NULL, ticks INTEGER NOT NULL, created REAL NOT NULL,
                source TEXT NOT NULL, status TEXT NOT NULL, evidence_id TEXT);
            CREATE INDEX IF NOT EXISTS pb_account ON pb_records(uuid, status);
            CREATE TABLE IF NOT EXISTS record_names (
                uuid TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS solo_attempts (
                id TEXT PRIMARY KEY, uuid TEXT NOT NULL, floor TEXT NOT NULL, started REAL NOT NULL,
                last_received REAL NOT NULL, sequence INTEGER NOT NULL, nonce TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL, ticks INTEGER NOT NULL, paul INTEGER NOT NULL,
                saw_low INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT);
            CREATE INDEX IF NOT EXISTS solo_account ON solo_attempts(uuid, started);
            CREATE TABLE IF NOT EXISTS solo_samples (
                attempt_id TEXT NOT NULL, sequence INTEGER NOT NULL, received REAL NOT NULL,
                body TEXT NOT NULL, PRIMARY KEY(attempt_id, sequence));
            CREATE TABLE IF NOT EXISTS terminal_groups (
                id TEXT PRIMARY KEY, floor TEXT NOT NULL, started_ms INTEGER NOT NULL,
                roster TEXT NOT NULL, created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS terminal_run ON terminal_groups(floor, roster, started_ms);
            CREATE TABLE IF NOT EXISTS terminal_reports (
                uuid TEXT NOT NULL, report_id TEXT NOT NULL, group_id TEXT NOT NULL,
                real_ms INTEGER NOT NULL, ticks INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(uuid, report_id), UNIQUE(uuid, group_id));
            CREATE TABLE IF NOT EXISTS evidence_holds (
                evidence_id TEXT NOT NULL, case_id TEXT NOT NULL, until REAL,
                PRIMARY KEY(evidence_id, case_id));
        """)
        with self.db:
            if not self.db.execute(
                "SELECT 1 FROM record_meta WHERE key='legacy_import'"
            ).fetchone():
                if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='mod_bests'").fetchone():
                    for row in self.db.execute("SELECT * FROM mod_bests").fetchall():
                        self._record(
                            row["uuid"],
                            row["floor"],
                            row["kind"],
                            row["real_ms"],
                            row["ticks"],
                            "legacy",
                            None,
                        )
                    # Old minima must not reappear after erasure or moderation.
                    self.db.execute("DROP TABLE mod_bests")
                self.db.execute("INSERT INTO record_meta VALUES ('legacy_import', 'done')")
            self.db.execute(
                "UPDATE solo_attempts SET status='abandoned',reason='service_restart' "
                "WHERE status='active'"
            )

    def _record(self, uuid, floor, kind, real_ms, ticks, source, evidence):
        record_id = secrets.token_urlsafe(32)
        self.db.execute(
            "INSERT INTO pb_records VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                record_id,
                uuid,
                floor,
                kind,
                real_ms,
                ticks,
                self.clock(),
                source,
                "eligible",
                evidence,
            ),
        )
        return record_id

    def read(self, uuid):
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT floor,kind,MIN(real_ms) AS real_ms,MIN(ticks) AS ticks "
                    "FROM pb_records WHERE uuid=? AND status='eligible' GROUP BY floor,kind",
                    (uuid,),
                )
            ]

    def start(self, uuid, body):
        with self.lock, self.db:
            now = self.clock()
            self.db.execute(
                "UPDATE solo_attempts SET "
                "status='abandoned',reason='connection_lost' WHERE "
                "status='active' AND last_received<?",
                (now - 15,),
            )
            recent = self.db.execute(
                "SELECT COUNT(*) FROM solo_attempts WHERE uuid=? AND started>?", (uuid, now - DAY)
            ).fetchone()[0]
            active = self.db.execute(
                "SELECT COUNT(*) FROM solo_attempts WHERE status='active'"
            ).fetchone()[0]
            if recent >= 500 or active >= 1000:
                raise HTTPException(429, "Attempt capacity reached. Try again later.")
            self.db.execute(
                "UPDATE solo_attempts SET "
                "status='abandoned',reason='new_attempt' WHERE uuid=? AND "
                "status='active'",
                (uuid,),
            )
            attempt, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO solo_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt,
                    uuid,
                    body.floor,
                    now - body.elapsed_ms / 1000,
                    now,
                    0,
                    nonce,
                    body.elapsed_ms,
                    body.ticks,
                    body.paul,
                    False,
                    "active",
                    None,
                ),
            )
            return {
                "version": 2,
                "attempt_id": attempt,
                "nonce": nonce,
                "sequence": 0,
                "status": "active",
            }

    def progress(self, uuid, body):
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM solo_attempts WHERE id=? AND uuid=?", (body.attempt_id, uuid)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Attempt unavailable")
            if row["status"] != "active":
                raise HTTPException(409, "Attempt is no longer active")
            now = self.clock()
            score = body.evidence.score(body.elapsed_ms, bool(row["paul"]))
            reason = self._invalid_progress(row, body, now, score)
            self.db.execute(
                "INSERT INTO solo_samples VALUES (?,?,?,?)",
                (
                    row["id"],
                    row["sequence"] + 1,
                    now,
                    body.model_dump_json(exclude={"nonce", "attempt_id"}),
                ),
            )
            if reason:
                self.db.execute(
                    "UPDATE solo_attempts SET status='rejected',reason=? WHERE id=?",
                    (reason, row["id"]),
                )
                # Return rejection inside the transaction so the evidence and result commit.
                return {"version": 2, "status": "rejected", "reason": reason}
            nonce = secrets.token_urlsafe(32)
            status = "accepted" if body.complete else "active"
            self.db.execute(
                "UPDATE solo_attempts SET "
                "last_received=?,sequence=?,nonce=?,elapsed_ms=?,ticks=?,saw_low=?,status=?"
                " WHERE id=?",
                (
                    now,
                    body.sequence,
                    nonce,
                    body.elapsed_ms,
                    body.ticks,
                    bool(row["saw_low"]) or (score is not None and score < 300),
                    status,
                    row["id"],
                ),
            )
            result = {
                "version": 2,
                "attempt_id": row["id"],
                "sequence": body.sequence,
                "nonce": nonce,
                "status": status,
            }
            if body.complete:
                result["record_id"] = self._record(
                    uuid, row["floor"], "solo_clear", body.elapsed_ms, body.ticks, "live", row["id"]
                )
            return result

    @staticmethod
    def _invalid_progress(row, body, now, score):
        if body.sequence != row["sequence"] + 1 or not secrets.compare_digest(
            body.nonce, row["nonce"]
        ):
            return "sequence"
        if now - row["last_received"] > 15 or now - row["started"] > 7200:
            return "connection_lost"
        if abs((now - row["started"]) * 1000 - body.elapsed_ms) > 5000:
            return "elapsed_time"
        if (
            body.elapsed_ms < row["elapsed_ms"]
            or (body.elapsed_ms == row["elapsed_ms"] and not body.complete)
            or body.ticks < row["ticks"]
        ):
            return "clock"
        if body.ticks > body.elapsed_ms / 50 + 40 or body.ticks < body.elapsed_ms / 250:
            return "tick_rate"
        return RecordStore._invalid_observation(row, body, now, score)

    @staticmethod
    def _invalid_observation(row, body, now, score):
        if body.roster != [row["uuid"]]:
            return "not_solo"
        if body.dead or (body.evidence.deaths or 0) > 0:
            return "death"
        if not body.valid:
            return "client_invalidated"
        if not body.complete and now - row["last_received"] < 1:
            return "update_rate"
        if body.complete and (
            score is None or score < 300 or not row["saw_low"] or body.sequence < 3
        ):
            return "incomplete_score"
        return None

    def terminal(self, uuid, body):
        encoded = body.model_dump_json()
        with self.lock, self.db:
            existing = self.db.execute(
                "SELECT * FROM terminal_reports WHERE uuid=? AND report_id=?",
                (uuid, body.report_id),
            ).fetchone()
            if existing:
                if existing["body"] != encoded:
                    raise HTTPException(409, "Report identifier already used")
                return self._terminal_result(existing["group_id"], uuid)
            now = self.clock()
            if uuid not in body.roster or len(set(body.roster)) != len(body.roster):
                raise HTTPException(422, "Invalid run roster")
            if (
                not now * 1000 - DAY * 1000 <= body.run_started_ms <= now * 1000
                or body.run_started_ms + body.real_ms > now * 1000 + 5000
            ):
                raise HTTPException(422, "Invalid run time")
            if body.ticks > body.real_ms / 50 + 40 or body.ticks < body.real_ms / 250:
                raise HTTPException(422, "Invalid tick rate")
            roster = json.dumps(sorted(body.roster))
            group = self.db.execute(
                "SELECT id FROM terminal_groups WHERE floor=? AND roster=? "
                "AND ABS(started_ms-?)<=10000 ORDER BY ABS(started_ms-?) "
                "LIMIT 1",
                (body.floor, roster, body.run_started_ms, body.run_started_ms),
            ).fetchone()
            group_id = group["id"] if group else secrets.token_urlsafe(32)
            if self.db.execute(
                "SELECT 1 FROM terminal_reports WHERE uuid=? AND group_id=?", (uuid, group_id)
            ).fetchone():
                raise HTTPException(409, "Account already reported this run")
            if (
                self.db.execute(
                    "SELECT COUNT(*) FROM pb_records WHERE uuid=? AND created>?", (uuid, now - DAY)
                ).fetchone()[0]
                >= 500
            ):
                raise HTTPException(429, "Report capacity reached")
            if not group:
                self.db.execute(
                    "INSERT INTO terminal_groups VALUES (?,?,?,?,?)",
                    (group_id, body.floor, body.run_started_ms, roster, now),
                )
            self.db.execute(
                "INSERT INTO terminal_reports VALUES (?,?,?,?,?,?)",
                (uuid, body.report_id, group_id, body.real_ms, body.ticks, encoded),
            )
            self._record(
                uuid, body.floor, "terminals", body.real_ms, body.ticks, "single_report", group_id
            )
            self._corroborate(group_id)
            return self._terminal_result(group_id, uuid)

    def _corroborate(self, group_id):
        reports = self.db.execute(
            "SELECT * FROM terminal_reports WHERE group_id=?", (group_id,)
        ).fetchall()
        if len(reports) > 1:
            conflict = (
                max(r["real_ms"] for r in reports) - min(r["real_ms"] for r in reports) > 1000
                or max(r["ticks"] for r in reports) - min(r["ticks"] for r in reports) > 20
            )
            # Preserve eligibility pending human review; a hostile witness cannot erase a PB.
            self.db.execute(
                "UPDATE pb_records SET source=? WHERE evidence_id=?",
                ("conflicting_reports" if conflict else "corroborated", group_id),
            )

    def _terminal_result(self, group, uuid):
        row = self.db.execute(
            "SELECT source FROM pb_records WHERE evidence_id=? AND uuid=? LIMIT 1", (group, uuid)
        ).fetchone()
        if row is None:
            return {"version": 2, "status": "rejected", "reason": "record_deleted"}
        return {"version": 2, "status": "accepted", "corroboration": row["source"]}

    def cleanup(self):
        with self.lock, self.db:
            now = self.clock()
            self.db.execute(
                "UPDATE solo_attempts SET "
                "status='abandoned',reason='connection_lost' WHERE "
                "status='active' AND last_received<?",
                (now - 15,),
            )
            self.db.execute(
                "DELETE FROM solo_attempts WHERE (started < ? - CASE WHEN "
                "status='accepted' THEN ? ELSE ? END OR EXISTS (SELECT 1 FROM "
                "evidence_holds WHERE evidence_id=solo_attempts.id AND until<=?)) "
                "AND NOT EXISTS (SELECT 1 FROM evidence_holds WHERE "
                "evidence_id=solo_attempts.id AND (until IS NULL OR until>?))",
                (now, 30 * DAY, 7 * DAY, now, now),
            )
            self.db.execute(
                "DELETE FROM solo_samples WHERE attempt_id NOT IN (SELECT id FROM solo_attempts)"
            )
            self.db.execute(
                "DELETE FROM terminal_groups WHERE (created<? OR EXISTS "
                "(SELECT 1 FROM evidence_holds WHERE evidence_id=terminal_groups.id "
                "AND until<=?)) AND NOT EXISTS (SELECT 1 FROM evidence_holds WHERE "
                "evidence_id=terminal_groups.id AND (until IS NULL OR until>?))",
                (now - 30 * DAY, now, now),
            )
            self.db.execute(
                "DELETE FROM terminal_reports WHERE group_id NOT IN "
                "(SELECT id FROM terminal_groups)"
            )
            self.db.execute(
                "DELETE FROM evidence_holds WHERE evidence_id NOT IN "
                "(SELECT id FROM solo_attempts UNION SELECT id FROM terminal_groups)"
            )

    def close(self):
        self.db.close()
