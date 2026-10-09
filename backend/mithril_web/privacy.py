"""Account erasure, with a separate seven-day restore ledger and atomic SQLite writes."""

import json
import os
import re
import secrets
from pathlib import Path

from fastapi import HTTPException

from .auth import DAY, digest


class Privacy:
    def __init__(self, auth, moderation, auth_path):
        self.auth, self.moderation = auth, moderation
        self.records, self.db = moderation.records, moderation.db
        self.clock = moderation.clock
        self.ledger = Path(auth_path).with_name("erasures.jsonl")
        required = self.db.execute(
            "SELECT 1 FROM record_meta WHERE key='privacy_ledger_required'"
        ).fetchone()
        if required and not self.ledger.is_file():
            raise ValueError("Missing erasure ledger; restore it before serving account data")
        self.ledger.touch(exist_ok=True, mode=0o600)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO record_meta VALUES ('privacy_ledger_required','yes')"
            )
        self.db.execute("ATTACH DATABASE ? AS accounts", (str(auth_path),))
        for schema in ("main", "accounts"):
            if self.db.execute(f"PRAGMA {schema}.journal_mode").fetchone()[0] not in (
                "delete",
                "truncate",
                "persist",
            ):
                raise ValueError("Atomic account erasure requires rollback journals")
            self.db.execute(f"PRAGMA {schema}.secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS erasures_applied (id TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts.erasures_applied (
                id TEXT PRIMARY KEY, at REAL NOT NULL);
        """)
        self.replay()

    def _events(self):
        events = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if (
                set(event) != {"id", "uuid", "scope", "at"}
                or not re.fullmatch(r"[a-f0-9]{32}", str(event["uuid"]))
                or not re.fullmatch(r"[a-f0-9]{32}", str(event["id"]))
                or event["scope"] not in ("records", "account")
                or not isinstance(event["at"], (int, float))
            ):
                raise ValueError("Invalid erasure ledger; do not serve restored data")
            events.append(event)
        return events

    def replay(self):
        with self.records.lock, self.auth.lock:
            for event in self._events():
                done = self.db.execute(
                    "SELECT 1 FROM erasures_applied WHERE id=?", (event["id"],)
                ).fetchone()
                auth_done = self.db.execute(
                    "SELECT 1 FROM accounts.erasures_applied WHERE id=?", (event["id"],)
                ).fetchone()
                if not (done and auth_done):
                    with self.db:
                        self._erase(event)

    def erase(self, token, scope, kind="session"):
        with self.records.lock, self.auth.lock:
            row = self.db.execute(
                "SELECT uuid FROM accounts.auth WHERE token=? AND kind=? AND expires>?",
                (digest(token), kind, self.clock()),
            ).fetchone()
            if not row:
                raise HTTPException(401, "Sign in first")
            event = {
                "id": secrets.token_hex(16),
                "uuid": row[0],
                "scope": scope,
                "at": self.clock(),
            }
            self._events()  # Refuse to append to a damaged recovery ledger.
            with self.ledger.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            with self.db:
                self._erase(event)
            return row[0]

    def _erase(self, event):
        uuid, now = event["uuid"], self.clock()
        self.db.execute("DELETE FROM pb_records WHERE uuid=?", (uuid,))
        self.db.execute("DELETE FROM record_names WHERE uuid=?", (uuid,))
        self.db.execute("DELETE FROM pb_maps WHERE uuid=?", (uuid,))
        self.db.execute("DELETE FROM curator_results WHERE uuid=?", (uuid,))
        self.db.execute(
            "DELETE FROM solo_samples WHERE attempt_id IN (SELECT id FROM solo_attempts "
            "WHERE uuid=? "
            "AND NOT EXISTS (SELECT 1 FROM evidence_holds WHERE evidence_id=solo_attempts.id "
            "AND (until IS NULL OR until>?)))",
            (uuid, now),
        )
        self.db.execute(
            "DELETE FROM solo_attempts WHERE uuid=? AND NOT EXISTS "
            "(SELECT 1 FROM evidence_holds WHERE evidence_id=solo_attempts.id "
            "AND (until IS NULL OR until>?))",
            (uuid, now),
        )
        self.db.execute(
            "DELETE FROM terminal_reports WHERE uuid=? AND NOT EXISTS "
            "(SELECT 1 FROM evidence_holds WHERE evidence_id=terminal_reports.group_id "
            "AND (until IS NULL OR until>?))",
            (uuid, now),
        )
        self.db.execute(
            "DELETE FROM terminal_groups WHERE id NOT IN (SELECT group_id FROM terminal_reports)"
        )
        # Minimize mentions in other people's unheld corroboration evidence.
        for row in self.db.execute(
            "SELECT uuid,report_id,body FROM terminal_reports WHERE NOT EXISTS "
            "(SELECT 1 FROM evidence_holds WHERE evidence_id=terminal_reports.group_id "
            "AND (until IS NULL OR until>?))",
            (now,),
        ).fetchall():
            body = json.loads(row["body"])
            if uuid in body.get("roster", []):
                body["roster"] = [member for member in body["roster"] if member != uuid]
                self.db.execute(
                    "UPDATE terminal_reports SET body=? WHERE uuid=? AND report_id=?",
                    (json.dumps(body), row["uuid"], row["report_id"]),
                )
        for row in self.db.execute(
            "SELECT id,roster FROM terminal_groups WHERE NOT EXISTS "
            "(SELECT 1 FROM evidence_holds WHERE evidence_id=terminal_groups.id "
            "AND (until IS NULL OR until>?))",
            (now,),
        ).fetchall():
            roster = json.loads(row["roster"])
            if uuid in roster:
                self.db.execute(
                    "UPDATE terminal_groups SET roster=? WHERE id=?",
                    (json.dumps([member for member in roster if member != uuid]), row["id"]),
                )
        if event["scope"] == "account":
            self.db.execute(
                "DELETE FROM accounts.link_codes WHERE link IN "
                "(SELECT token FROM accounts.auth WHERE uuid=?)",
                (uuid,),
            )
            self.db.execute("DELETE FROM accounts.auth WHERE uuid=?", (uuid,))
            self.db.execute("DELETE FROM moderators WHERE uuid=?", (uuid,))
            self.db.execute("DELETE FROM account_networks WHERE uuid=?", (uuid,))
            self.db.execute("UPDATE chat_reports SET reporter='erased' WHERE reporter=?", (uuid,))
            self.db.execute(
                "DELETE FROM chat_reports WHERE uuid=? AND status!='open' AND NOT EXISTS "
                "(SELECT 1 FROM chat_evidence_holds WHERE report_id=chat_reports.id "
                "AND (until IS NULL OR until>?))",
                (uuid, now),
            )
        else:
            self.db.execute(
                "DELETE FROM accounts.auth WHERE uuid=? AND kind IN ('sync','sync_challenge')",
                (uuid,),
            )
        # Prevent a proof already in flight from minting new credentials after this transaction.
        self.db.execute(
            "INSERT OR REPLACE INTO accounts.auth_epochs VALUES (?,?,?)",
            (uuid, secrets.token_hex(16), now),
        )
        for table in ("erasures_applied", "accounts.erasures_applied"):
            self.db.execute(
                f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (event["id"], event["at"])
            )

    def cleanup(self):
        with self.records.lock, self.auth.lock:
            cutoff = self.clock() - 7 * DAY
            events = [event for event in self._events() if event["at"] > cutoff]
            temporary = self.ledger.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write("".join(json.dumps(event) + "\n" for event in events))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.ledger)
            with self.db:
                for table in ("erasures_applied", "accounts.erasures_applied"):
                    self.db.execute(f"DELETE FROM {table} WHERE at<=?", (cutoff,))
