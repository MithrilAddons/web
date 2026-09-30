"""Only reported messages are persisted; ordinary party chat remains ephemeral."""

import json
import secrets

from fastapi import HTTPException

from .record_store import DAY


class ChatReports:
    def __init__(self, moderation):
        self.moderation = moderation
        self.db, self.lock, self.clock = moderation.db, moderation.lock, moderation.clock
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chat_reports (
                id TEXT PRIMARY KEY, reporter TEXT NOT NULL, uuid TEXT NOT NULL,
                party_id TEXT NOT NULL, message_id TEXT NOT NULL, created REAL NOT NULL,
                reason TEXT NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL,
                UNIQUE(reporter,party_id,message_id));
            CREATE TABLE IF NOT EXISTS chat_evidence_holds (
                report_id TEXT NOT NULL, case_id TEXT NOT NULL, until REAL,
                PRIMARY KEY(report_id,case_id));
        """)

    def submit(self, reporter, party_id, message, reason):
        with self.lock, self.db:
            self.moderation._check(reporter)
            old = self.db.execute(
                "SELECT id FROM chat_reports WHERE reporter=? AND party_id=? AND message_id=?",
                (reporter, party_id, message["id"]),
            ).fetchone()
            if old:
                return old[0]
            if (
                self.db.execute("SELECT COUNT(*) FROM chat_reports").fetchone()[0] >= 10000
                or self.db.execute(
                    "SELECT COUNT(*) FROM chat_reports WHERE reporter=? AND created>?",
                    (reporter, self.clock() - DAY),
                ).fetchone()[0]
                >= 10
            ):
                raise HTTPException(429, "Report limit reached; try again tomorrow")
            report_id = secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO chat_reports VALUES (?,?,?,?,?,?,?,?, 'open')",
                (
                    report_id,
                    reporter,
                    message["sender"]["uuid"],
                    party_id,
                    message["id"],
                    self.clock(),
                    reason,
                    json.dumps(message),
                ),
            )
            return report_id

    def list(self, actor):
        with self.lock:
            self.moderation._require(actor)
            return {
                "version": 1,
                "reports": [
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM chat_reports WHERE status='open' ORDER BY created LIMIT 100"
                    )
                ],
            }

    def resolve(self, actor, report_id, action, reason):
        with self.lock, self.db:
            self.moderation._require(actor)
            row = self.db.execute("SELECT * FROM chat_reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Report not found or evidence expired")
            if row["status"] != "open":
                raise HTTPException(409, "Report already reviewed")
            self.db.execute("UPDATE chat_reports SET status=? WHERE id=?", (action, report_id))
            # Audit records the decision, not a permanent copy of expiring message evidence.
            self.moderation._audit(
                actor,
                f"chat_{action}",
                row["uuid"],
                reason,
                {"report_id": report_id, "status": "open"},
                {"report_id": report_id, "status": action},
            )
            return row["party_id"], row["message_id"]

    def cleanup(self):
        with self.lock, self.db:
            now = self.clock()
            self.db.execute(
                "DELETE FROM chat_reports WHERE (created<=? OR EXISTS (SELECT 1 FROM "
                "chat_evidence_holds WHERE report_id=chat_reports.id AND until<=?)) "
                "AND NOT EXISTS (SELECT 1 FROM chat_evidence_holds WHERE report_id=chat_reports.id "
                "AND (until IS NULL OR until>?))",
                (now - 30 * DAY, now, now),
            )
            self.db.execute(
                "DELETE FROM chat_evidence_holds WHERE report_id NOT IN "
                "(SELECT id FROM chat_reports)"
            )
