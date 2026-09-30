"""Moderator actions share the records transaction so every change has an audit entry."""

import hashlib
import hmac
import ipaddress
import json
import re
import secrets

from fastapi import HTTPException

from .chat_reports import ChatReports
from .record_store import DAY


class Moderation:
    def __init__(self, records, owner=None, network_key=None):
        if owner and not re.fullmatch(r"[0-9a-f]{32}", owner):
            raise ValueError("MITHRIL_OWNER_UUID must be a lowercase, unhyphenated UUID")
        if network_key and len(network_key) < 32:
            raise ValueError("The moderation network key must contain at least 32 bytes")
        self.records, self.owner, self.network_key = records, owner, network_key
        self.db, self.lock, self.clock = records.db, records.lock, records.clock
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS moderators (uuid TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS moderation_audit (
                id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, subject TEXT NOT NULL, reason TEXT NOT NULL,
                before_json TEXT NOT NULL, after_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sanctions (
                id TEXT PRIMARY KEY, uuid TEXT NOT NULL, kind TEXT NOT NULL,
                created REAL NOT NULL, expires REAL, revoked REAL, reason TEXT NOT NULL,
                actor TEXT NOT NULL, appeal_open INTEGER NOT NULL, evidence_until REAL NOT NULL,
                network TEXT);
            CREATE INDEX IF NOT EXISTS sanction_account ON sanctions(uuid, kind);
            CREATE INDEX IF NOT EXISTS sanction_network ON sanctions(network);
            CREATE TABLE IF NOT EXISTS case_activity (id TEXT PRIMARY KEY, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS account_networks (
                uuid TEXT PRIMARY KEY, network TEXT NOT NULL, seen REAL NOT NULL);
        """)

        self.chat = ChatReports(self)

    def _role(self, uuid):
        if uuid == self.owner:
            return "owner"
        if self.db.execute("SELECT 1 FROM moderators WHERE uuid=?", (uuid,)).fetchone():
            return "moderator"
        return None

    def role(self, uuid):
        with self.lock:
            return self._role(uuid)

    def _require(self, actor, owner=False):
        role = self._role(actor)
        if not role or (owner and role != "owner"):
            raise HTTPException(
                403, "Owner access required" if owner else "Moderator access required"
            )
        self._check(actor)
        return role

    def _audit(self, actor, action, subject, reason, before, after):
        self.db.execute(
            "INSERT INTO moderation_audit(at,actor,action,subject,reason,before_json,after_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.clock(), actor, action, subject, reason, json.dumps(before), json.dumps(after)),
        )

    def home(self, actor):
        with self.lock:
            role = self._require(actor)
            return {
                "version": 1,
                "role": role,
                "network_bans_available": bool(self.network_key),
                "moderators": [
                    r[0] for r in self.db.execute("SELECT uuid FROM moderators ORDER BY uuid")
                ],
            }

    def grant(self, actor, uuid, enabled, reason):
        with self.lock, self.db:
            self._require(actor, owner=True)
            if uuid == self.owner:
                raise HTTPException(409, "Owner access is configured separately")
            before = self._role(uuid)
            if enabled:
                self.db.execute("INSERT OR IGNORE INTO moderators VALUES (?)", (uuid,))
            else:
                self.db.execute("DELETE FROM moderators WHERE uuid=?", (uuid,))
            self._audit(
                actor,
                "moderator_grant" if enabled else "moderator_revoke",
                uuid,
                reason,
                before,
                self._role(uuid),
            )

    def inspect(self, actor, uuid):
        with self.lock:
            self._require(actor)
            records = [
                dict(r)
                for r in self.db.execute(
                    """WITH ranked AS (
                        SELECT id,status,
                            ROW_NUMBER() OVER (ORDER BY created DESC,id) AS recent,
                            ROW_NUMBER() OVER (PARTITION BY floor,kind
                                ORDER BY status='eligible' DESC,real_ms,id) AS real_rank,
                            ROW_NUMBER() OVER (PARTITION BY floor,kind
                                ORDER BY status='eligible' DESC,ticks,id) AS tick_rank
                        FROM pb_records WHERE uuid=?)
                    SELECT * FROM pb_records WHERE id IN (SELECT id FROM ranked
                        WHERE recent<=200 OR (status='eligible' AND (real_rank=1 OR tick_rank=1)))
                    ORDER BY created DESC,id""",
                    (uuid,),
                )
            ]
            cases = [
                self._case(r)
                for r in self.db.execute(
                    "SELECT * FROM sanctions WHERE uuid=? ORDER BY created DESC,id LIMIT 100",
                    (uuid,),
                )
            ]
            return {"version": 1, "uuid": uuid, "records": records, "cases": cases}

    def audit(self, actor, before):
        with self.lock:
            self._require(actor)
            rows = self.db.execute(
                "SELECT * FROM moderation_audit WHERE id<? ORDER BY id DESC LIMIT 100", (before,)
            ).fetchall()
            return {"version": 1, "entries": [dict(r) for r in rows]}

    def record_action(self, actor, body):
        with self.lock, self.db:
            self._require(actor)
            row = self.db.execute(
                "SELECT * FROM pb_records WHERE id=?", (body.record_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Record not found")
            before = dict(row)
            if row["status"] != body.expected_status:
                raise HTTPException(409, "Record changed; reload before editing")
            status = "eligible" if body.action == "restore" else "invalidated"
            if status == row["status"]:
                raise HTTPException(409, "Record already has that status")
            self.db.execute("UPDATE pb_records SET status=? WHERE id=?", (status, row["id"]))
            after = {**before, "status": status}
            if body.action == "correct":
                new_id = self.records._record(
                    row["uuid"], row["floor"], row["kind"], body.real_ms, body.ticks, "manual", None
                )
                after = {
                    "previous": after,
                    "replacement": dict(
                        self.db.execute("SELECT * FROM pb_records WHERE id=?", (new_id,)).fetchone()
                    ),
                }
            self._audit(actor, f"record_{body.action}", row["uuid"], body.reason, before, after)
            return row["uuid"]

    def evidence(self, actor, record_id):
        with self.lock:
            self._require(actor)
            row = self.db.execute(
                "SELECT evidence_id FROM pb_records WHERE id=?", (record_id,)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Record not found")
            evidence_id = row[0]
            # Do not expose rolling challenge nonces, credentials or connection identifiers.
            samples = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM solo_samples WHERE attempt_id=? ORDER BY sequence",
                    (evidence_id,),
                )
            ]
            reports = [
                json.loads(r[0])
                for r in self.db.execute(
                    "SELECT body FROM terminal_reports WHERE group_id=?", (evidence_id,)
                )
            ]
            return {
                "version": 1,
                "available": bool(samples or reports),
                "samples": samples,
                "reports": reports,
            }

    @staticmethod
    def _case(row):
        return {k: row[k] for k in row.keys() if k != "network"}

    def case_evidence(self, actor, case_id):
        with self.lock:
            self._require(actor)
            if not self.db.execute("SELECT 1 FROM sanctions WHERE id=?", (case_id,)).fetchone():
                raise HTTPException(404, "Case not found")
            samples = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT body FROM solo_samples WHERE attempt_id IN "
                    "(SELECT evidence_id FROM evidence_holds WHERE case_id=?) ORDER BY sequence",
                    (case_id,),
                )
            ]
            terminals = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT body FROM terminal_reports WHERE group_id IN "
                    "(SELECT evidence_id FROM evidence_holds WHERE case_id=?)",
                    (case_id,),
                )
            ]
            chat = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT evidence FROM chat_reports WHERE id IN "
                    "(SELECT report_id FROM chat_evidence_holds WHERE case_id=?)",
                    (case_id,),
                )
            ]
            return {
                "version": 1,
                "available": bool(samples or terminals or chat),
                "samples": samples,
                "reports": terminals,
                "chat": chat,
            }

    def sanction(self, actor, body):
        with self.lock, self.db:
            self._require(actor)
            if body.uuid == self.owner:
                raise HTTPException(409, "The owner cannot be sanctioned")
            now = self.clock()
            if body.expires is not None and not now < body.expires <= now + 3650 * DAY:
                raise HTTPException(422, "Expiry must be in the next ten years; omit for permanent")
            network = None
            if body.kind == "network_ban":
                peer = self.db.execute(
                    "SELECT network FROM account_networks WHERE uuid=? AND seen>?",
                    (body.uuid, now - DAY),
                ).fetchone()
                if not self.network_key or not peer:
                    raise HTTPException(409, "No recent authenticated connection is available")
                network = peer[0]
            case_id = secrets.token_urlsafe(32)
            until = body.expires if body.expires is not None else now + 30 * DAY
            self.db.execute(
                "INSERT INTO sanctions VALUES (?,?,?,?,?,NULL,?,?,0,?,?)",
                (
                    case_id,
                    body.uuid,
                    body.kind,
                    now,
                    body.expires,
                    body.reason,
                    actor,
                    until,
                    network,
                ),
            )
            for record_id in body.record_ids:
                record = self.db.execute(
                    "SELECT evidence_id FROM pb_records WHERE id=? AND uuid=?",
                    (record_id, body.uuid),
                ).fetchone()
                if not record:
                    raise HTTPException(422, "Evidence must belong to the sanctioned account")
                if record[0]:
                    self.db.execute(
                        "INSERT OR IGNORE INTO evidence_holds VALUES (?,?,?)",
                        (record[0], case_id, until),
                    )
            for report_id in body.report_ids:
                if not self.db.execute(
                    "SELECT 1 FROM chat_reports WHERE id=? AND uuid=?", (report_id, body.uuid)
                ).fetchone():
                    raise HTTPException(422, "Chat evidence must belong to the sanctioned account")
                self.db.execute(
                    "INSERT OR IGNORE INTO chat_evidence_holds VALUES (?,?,?)",
                    (report_id, case_id, until),
                )
            result = self._case(
                self.db.execute("SELECT * FROM sanctions WHERE id=?", (case_id,)).fetchone()
            )
            self.db.execute("INSERT INTO case_activity VALUES (?,?)", (case_id, now))
            self._audit(actor, "sanction", body.uuid, body.reason, None, result)
            return result

    def case_action(self, actor, body):
        with self.lock, self.db:
            self._require(actor)
            row = self.db.execute("SELECT * FROM sanctions WHERE id=?", (body.case_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Case not found")
            before = self._case(row)
            appeal, revoked, until = row["appeal_open"], row["revoked"], row["evidence_until"]
            if body.action == "revoke":
                if revoked is not None:
                    raise HTTPException(409, "Sanction already revoked")
                revoked, until = self.clock(), min(until, self.clock())
            else:
                wanted = int(body.action == "open_appeal")
                if appeal == wanted:
                    raise HTTPException(409, "Appeal already has that state")
                appeal = wanted
            self.db.execute(
                "UPDATE sanctions SET revoked=?,appeal_open=?,evidence_until=? WHERE id=?",
                (revoked, appeal, until, row["id"]),
            )
            self.db.execute(
                "UPDATE evidence_holds SET until=? WHERE case_id=?",
                (None if appeal else until, row["id"]),
            )
            self.db.execute(
                "UPDATE chat_evidence_holds SET until=? WHERE case_id=?",
                (None if appeal else until, row["id"]),
            )
            after = self._case(
                self.db.execute("SELECT * FROM sanctions WHERE id=?", (row["id"],)).fetchone()
            )
            self.db.execute(
                "INSERT OR REPLACE INTO case_activity VALUES (?,?)", (row["id"], self.clock())
            )
            self._audit(actor, body.action, row["uuid"], body.reason, before, after)
            return after

    def _fingerprint(self, address):
        if not self.network_key or not address:
            return None
        try:
            address = ipaddress.ip_address(address)
        except ValueError:
            return None
        address = getattr(address, "ipv4_mapped", None) or address
        return hmac.new(self.network_key, address.packed, hashlib.sha256).hexdigest()

    def _check(self, uuid, network=None, chat=False):
        if uuid == self.owner:
            return
        row = self.db.execute(
            "SELECT kind FROM sanctions WHERE revoked IS NULL AND (expires IS NULL OR expires>?) "
            "AND ((uuid=? AND kind IN ('ban','network_ban')) OR (network=? AND kind='network_ban') "
            "OR (uuid=? AND kind='mute' AND ?)) LIMIT 1",
            (self.clock(), uuid, network, uuid, chat),
        ).fetchone()
        if row:
            raise HTTPException(
                403, "Chat muted" if row[0] == "mute" else "Account or connection banned"
            )

    def check(self, uuid, address=None, chat=False, remember=False):
        with self.lock, self.db:
            network = self._fingerprint(address)
            self._check(uuid, network, chat)
            if remember and network:
                self.db.execute(
                    "INSERT INTO account_networks VALUES (?,?,?) ON CONFLICT(uuid) "
                    "DO UPDATE SET network=excluded.network,seen=excluded.seen",
                    (uuid, network, self.clock()),
                )

    def affected_accounts(self, case):
        with self.lock:
            row = self.db.execute(
                "SELECT network FROM sanctions WHERE id=?", (case["id"],)
            ).fetchone()
            uuids = {case["uuid"]}
            if row and row[0]:
                uuids.update(
                    r[0]
                    for r in self.db.execute(
                        "SELECT uuid FROM account_networks WHERE network=? AND seen>?",
                        (row[0], self.clock() - DAY),
                    )
                )
            return uuids - {self.owner}

    def cleanup(self):
        self.chat.cleanup()
        with self.lock, self.db:
            self.db.execute("DELETE FROM account_networks WHERE seen<=?", (self.clock() - DAY,))
            self.db.execute(
                "UPDATE sanctions SET network=NULL WHERE revoked IS NOT NULL "
                "OR (expires IS NOT NULL AND expires<=?)",
                (self.clock(),),
            )

            self.db.execute(
                "DELETE FROM sanctions WHERE appeal_open=0 AND "
                "COALESCE(revoked,expires) IS NOT NULL AND COALESCE(revoked,expires)<=? "
                "AND COALESCE((SELECT at FROM case_activity WHERE id=sanctions.id),created)<=?",
                (self.clock() - 180 * DAY, self.clock() - 180 * DAY),
            )
            self.db.execute("DELETE FROM case_activity WHERE id NOT IN (SELECT id FROM sanctions)")
            self.db.execute(
                "DELETE FROM moderation_audit WHERE at<=? AND NOT EXISTS "
                "(SELECT 1 FROM sanctions WHERE uuid=moderation_audit.subject)",
                (self.clock() - 180 * DAY,),
            )
