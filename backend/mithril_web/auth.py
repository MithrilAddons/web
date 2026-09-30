"""Single-use Minecraft proofs and opaque browser sessions. No game tokens received."""

import hashlib
import http.client
import ipaddress
import json
import math
import secrets
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException

COOKIE = "__Host-mithril_session"
DAY = 86400
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PENDING_LIMIT = 1000
CREDENTIAL_LIMIT = 100000


class AuthAttempts:
    """Bound anonymous work and limiter memory; denied attempts do not extend the window."""

    def __init__(self, per_client, total, clock=time.monotonic):
        self.per_client, self.total, self.clock = per_client, total, clock
        self.lock = threading.Lock()
        self.attempts = deque()

    def check(self, client):
        # Use the ASGI peer, never a caller-supplied forwarding header. A /64 groups
        # IPv6 privacy addresses; IPv4-mapped IPv6 shares the IPv4 client's budget.
        try:
            address = ipaddress.ip_address(client)
            if isinstance(address, ipaddress.IPv6Address):
                address = address.ipv4_mapped or ipaddress.ip_network(f"{address}/64", strict=False)
            client = str(address)
        except ValueError:
            client = "unknown"
        with self.lock:
            now = self.clock()
            while self.attempts and self.attempts[0][0] <= now - 60:
                self.attempts.popleft()
            own = [at for at, peer in self.attempts if peer == client]
            deadlines = []
            if len(self.attempts) >= self.total:
                deadlines.append(self.attempts[0][0] + 60)
            if len(own) >= self.per_client:
                deadlines.append(own[0] + 60)
            if deadlines:
                raise HTTPException(
                    429,
                    "Too many authentication attempts. Try again shortly.",
                    headers={"Retry-After": str(max(1, math.ceil(max(deadlines) - now)))},
                )
            self.attempts.append((now, client))


class CodeAttempts:
    """Bound short-code guessing across preview/completion, even without a proxy."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.attempts = deque()

    def check(self, client):
        with self.lock:
            now = self.clock()
            while self.attempts and self.attempts[0][0] <= now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 100 or sum(ip == client for _, ip in self.attempts) >= 10:
                raise HTTPException(429, "Too many code attempts. Wait a minute and try again.")
            self.attempts.append((now, client))


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def mojang_profile(name, server_id):
    connection = http.client.HTTPSConnection("sessionserver.mojang.com", timeout=5)
    try:
        query = urlencode({"username": name, "serverId": server_id})
        connection.request(
            "GET",
            f"/session/minecraft/hasJoined?{query}",
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("Ownership not verified")
        body = response.read(16385)
        if len(body) > 16384:
            raise ValueError("Response too large")
        return json.loads(body)
    finally:
        connection.close()


class AuthStore:
    """One lock owns SQLite; network calls never hold it. Tokens are hashed at rest."""

    def __init__(self, path: Path, clock=time.time):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS auth_epochs "
            "(uuid TEXT PRIMARY KEY, epoch TEXT NOT NULL, at REAL NOT NULL)"
        )
        self.db.execute("""CREATE TABLE IF NOT EXISTS auth (
            token TEXT PRIMARY KEY, kind TEXT NOT NULL, uuid TEXT NOT NULL, name TEXT NOT NULL,
            expires REAL NOT NULL, server_id TEXT, remembered INTEGER NOT NULL DEFAULT 0)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS auth_expiry ON auth(expires)")
        self.db.execute("CREATE INDEX IF NOT EXISTS auth_kind ON auth(kind, remembered)")
        self.db.execute("CREATE INDEX IF NOT EXISTS auth_parent ON auth(server_id, kind)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS link_codes (
            code TEXT PRIMARY KEY, link TEXT NOT NULL UNIQUE, expires REAL NOT NULL)""")
        self.db.commit()
        self.cleanup()

    def close(self):
        self.db.close()

    def cleanup(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth_epochs WHERE at<?", (self.clock() - 900,))
            self.db.execute("DELETE FROM auth WHERE expires <= ?", (self.clock(),))
            # Also reclaim legacy children whose parent was revoked or expired.
            self.db.execute("""DELETE FROM auth WHERE
                (kind IN ('sync', 'party') OR (kind='receipt' AND remembered=1))
                AND NOT EXISTS (SELECT 1 FROM auth AS parent WHERE
                    parent.token=auth.server_id AND parent.kind IN ('session','device')
                    AND parent.uuid=auth.uuid)""")
            self.db.execute("DELETE FROM link_codes WHERE expires <= ?", (self.clock(),))

    def issue_code(self, link_token):
        with self.lock, self.db:
            return self._issue_code(link_token)

    # Private write helpers require the caller to own both the lock and transaction.
    def _issue_code(self, link_token):
        self.db.execute("DELETE FROM link_codes WHERE expires <= ?", (self.clock(),))
        row = self.db.execute(
            "SELECT expires FROM auth WHERE token=? AND kind='link' AND expires>?",
            (digest(link_token), self.clock()),
        ).fetchone()
        if row is None:
            raise ValueError("Missing link")
        for _ in range(10):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
            if self.db.execute("SELECT 1 FROM link_codes WHERE code=?", (digest(code),)).fetchone():
                continue
            self.db.execute(
                "INSERT INTO link_codes VALUES (?,?,?)",
                (digest(code), digest(link_token), row["expires"]),
            )
            return code[:4] + "-" + code[4:]
        raise HTTPException(503, "Please try again later")

    def issue_link(self, uuid, name, expected_epoch=None):
        with self.lock, self.db:
            self._check_epoch(uuid, expected_epoch)
            token = self._issue("link", uuid, name, 300)
            receipt = self._issue("receipt", uuid, name, 300, server_id=digest(token))
            code = self._issue_code(token)
            return token, receipt, code

    def get_link(self, token, consume=False):
        # Both spellings point at one atomic redemption; neither secret is stored raw.
        with self.lock, self.db:
            return self._get_link(token, consume)

    def _get_link(self, token, consume=False):
        key = digest(token)
        if len(token) != 43:
            code = token.replace("-", "").upper()
            alias = self.db.execute(
                "SELECT link FROM link_codes WHERE code=? AND expires>?",
                (digest(code), self.clock()),
            ).fetchone()
            if alias is None:
                return None
            key = alias["link"]
        row = self.db.execute("SELECT * FROM auth WHERE token=? AND kind='link'", (key,)).fetchone()
        if row and (consume or row["expires"] <= self.clock()):
            self.db.execute("DELETE FROM auth WHERE token=?", (key,))
            self.db.execute("DELETE FROM link_codes WHERE link=?", (key,))
        return dict(row) if row and row["expires"] > self.clock() else None

    def finish_link(self, link_token, session_token, remember=None):
        """Redeem and confirm together; None resumes the existing browser session."""
        with self.lock, self.db:
            row = self._get_link(link_token, consume=True)
            if not row:
                raise HTTPException(
                    410, "Link expired or already used. Create another in Minecraft."
                )
            if remember is None:
                session = self.db.execute(
                    "SELECT * FROM auth WHERE token=? AND kind='session' AND expires>?",
                    (digest(session_token), self.clock()),
                ).fetchone()
                if not session or session["uuid"] != row["uuid"]:
                    raise HTTPException(409, "Confirm this account before signing in")
                remember = bool(session["remembered"])
                self._renew(session_token)
            else:
                # Free this browser's slot first, but restore everything if issuance fails.
                self._revoke(session_token)
                session_token = self._issue(
                    "session",
                    row["uuid"],
                    row["name"],
                    30 * DAY if remember else DAY,
                    remembered=remember,
                )
            self._confirm_link_hash(row["token"], session_token)
            return row, session_token, remember

    def issue(
        self, kind, uuid, name, seconds, server_id=None, remembered=False, *, expected_epoch=None
    ):
        with self.lock, self.db:
            self._check_epoch(uuid, expected_epoch)
            return self._issue(kind, uuid, name, seconds, server_id, remembered)

    def _epoch(self, uuid):
        row = self.db.execute("SELECT epoch FROM auth_epochs WHERE uuid=?", (uuid,)).fetchone()
        return row[0] if row else ""

    def _check_epoch(self, uuid, expected):
        if expected is not None and expected != self._epoch(uuid):
            raise HTTPException(401, "Account changed; start a new ownership proof")

    def _check_capacity(self, kind, remembered=False, additional=1):
        query, params = "SELECT COUNT(*) FROM auth WHERE kind=?", [kind]
        if kind == "receipt":
            query += " AND remembered=?"
            params.append(remembered)
        count = self.db.execute(query, params).fetchone()[0]
        established = kind in ("session", "device", "party", "sync") or (
            kind == "receipt" and remembered
        )
        if count + additional > (CREDENTIAL_LIMIT if established else PENDING_LIMIT):
            raise HTTPException(503, "Please try again later")

    def _issue(self, kind, uuid, name, seconds, server_id=None, remembered=False):
        token = secrets.token_urlsafe(32)
        self.db.execute("DELETE FROM auth WHERE expires <= ?", (self.clock(),))
        if kind == "party":
            # A fresh ownership proof replaces this browser link's previous credential.
            self.db.execute(
                "DELETE FROM auth WHERE kind='party' AND uuid=? AND server_id=?",
                (uuid, server_id),
            )
        self._check_capacity(kind, remembered)
        self.db.execute(
            "INSERT INTO auth VALUES (?,?,?,?,?,?,?)",
            (digest(token), kind, uuid, name, self.clock() + seconds, server_id, remembered),
        )
        return token

    def get(self, token, kind, consume=False):
        if not token:
            return None
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT * FROM auth WHERE token=? AND kind=?", (digest(token), kind)
            ).fetchone()
            if row and (consume or row["expires"] <= self.clock()):
                self.db.execute("DELETE FROM auth WHERE token=?", (digest(token),))
            if not row or row["expires"] <= self.clock():
                return None
            result = dict(row)
            if kind.endswith("challenge"):
                result["_epoch"] = self._epoch(row["uuid"])
            return result

    def revoke(self, token):
        with self.lock, self.db:
            self._revoke(token)

    def issue_device(self, uuid, name, expected_epoch):
        """A native session and its scoped-proof receipt are committed together."""
        with self.lock, self.db:
            self._check_epoch(uuid, expected_epoch)
            count = self.db.execute(
                "SELECT COUNT(*) FROM auth WHERE uuid=? AND kind='device' AND expires>?",
                (uuid, self.clock()),
            ).fetchone()[0]
            if count >= 10:
                raise HTTPException(409, "Remove an old Minecraft session before signing in")
            token = self._issue("device", uuid, name, 30 * DAY)
            receipt = self._issue(
                "receipt", uuid, name, 30 * DAY, server_id=digest(token), remembered=True
            )
            return token, receipt

    def devices(self, session_token):
        with self.lock:
            owner = self.db.execute(
                "SELECT uuid FROM auth WHERE token=? AND kind='session' AND expires>?",
                (digest(session_token), self.clock()),
            ).fetchone()
            if not owner:
                raise HTTPException(401, "Sign in first")
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT token AS id, name, expires FROM auth "
                    "WHERE uuid=? AND kind='device' AND expires>? ORDER BY expires DESC",
                    (owner["uuid"], self.clock()),
                )
            ]

    def revoke_device(self, token, device_id=None):
        with self.lock, self.db:
            if device_id is not None:
                owner = self.db.execute(
                    "SELECT uuid FROM auth WHERE token=? AND kind='session' AND expires>?",
                    (digest(token), self.clock()),
                ).fetchone()
                if not owner:
                    raise HTTPException(401, "Sign in first")
                row = self.db.execute(
                    "SELECT token FROM auth WHERE token=? AND kind='device' AND uuid=?",
                    (device_id, owner["uuid"]),
                ).fetchone()
                if not row:
                    raise HTTPException(404, "Minecraft session unavailable")
            else:
                device_id = digest(token)
                if not self.db.execute(
                    "SELECT 1 FROM auth WHERE token=? AND kind='device'", (device_id,)
                ).fetchone():
                    return
            self.db.execute("DELETE FROM auth WHERE token=? AND kind='device'", (device_id,))
            self.db.execute(
                "DELETE FROM auth WHERE server_id=? AND kind IN ('receipt','party','sync')",
                (device_id,),
            )

    def _revoke(self, token):
        self.db.execute("DELETE FROM auth WHERE token=? AND kind='session'", (digest(token),))
        self.db.execute(
            "DELETE FROM auth WHERE server_id=? AND "
            "(kind IN ('sync', 'party') OR (kind='receipt' AND remembered=1))",
            (digest(token),),
        )

    def confirm_receipts(self, link_token, session_token):
        self.confirm_link_hash(digest(link_token), session_token)

    def confirm_link_hash(self, link_hash, session_token):
        with self.lock, self.db:
            self._confirm_link_hash(link_hash, session_token)

    def _confirm_link_hash(self, link_hash, session_token):
        session = self.db.execute(
            "SELECT uuid, expires FROM auth WHERE token=? AND kind='session' AND expires>?",
            (digest(session_token), self.clock()),
        ).fetchone()
        if not session:
            raise HTTPException(401, "Session expired")
        self.db.execute("DELETE FROM auth WHERE expires <= ?", (self.clock(),))
        pending = self.db.execute(
            "SELECT COUNT(*) FROM auth WHERE kind='receipt' AND server_id=? "
            "AND remembered=0 AND uuid=?",
            (link_hash, session["uuid"]),
        ).fetchone()[0]
        self._check_capacity("receipt", remembered=True, additional=pending)
        self.db.execute(
            "UPDATE auth SET server_id=?, expires=?, remembered=1 "
            "WHERE kind='receipt' AND server_id=? AND remembered=0 AND uuid=?",
            (digest(session_token), session["expires"], link_hash, session["uuid"]),
        )

    def receipt_status(self, token):
        row = self.get(token, "receipt")
        if not row:
            return {"version": 1, "status": "expired"}
        if not row["remembered"]:
            return {"version": 1, "status": "pending"}
        with self.lock:
            session = self.db.execute(
                "SELECT uuid, name FROM auth WHERE token=? "
                "AND kind IN ('session','device') AND expires>?",
                (row["server_id"], self.clock()),
            ).fetchone()
        if not session:
            return {"version": 1, "status": "expired"}
        return {"version": 1, "status": "linked", "user": dict(session)}

    def linked_receipt(self, token):
        row = self.get(token, "receipt")
        if not row or not row["remembered"]:
            return None
        with self.lock:
            session = self.db.execute(
                "SELECT * FROM auth WHERE token=? "
                "AND kind IN ('session','device') AND uuid=? AND expires>?",
                (row["server_id"], row["uuid"], self.clock()),
            ).fetchone()
        return dict(session) if session else None

    def sync_identity(self, token):
        return self._scoped_identity(token, "sync")

    def party_identity(self, token):
        return self._scoped_identity(token, "party")

    def _scoped_identity(self, token, kind):
        row = self.get(token, kind)
        if not row:
            return None
        with self.lock:
            session = self.db.execute(
                "SELECT uuid, name FROM auth WHERE token=? AND kind IN ('session','device') "
                "AND uuid=? AND expires>?",
                (row["server_id"], row["uuid"], self.clock()),
            ).fetchone()
        return dict(session) if session else None

    def renew(self, token):
        with self.lock, self.db:
            self._renew(token)

    def _renew(self, token):
        session = self.db.execute(
            "SELECT remembered FROM auth WHERE token=? AND kind='session' AND expires>?",
            (digest(token), self.clock()),
        ).fetchone()
        if session is None:
            raise HTTPException(401, "Session expired")
        expires = self.clock() + (30 * DAY if session["remembered"] else DAY)
        self.db.execute(
            "UPDATE auth SET expires=? WHERE token=? AND kind='session'",
            (expires, digest(token)),
        )
        self.db.execute(
            "UPDATE auth SET expires=? WHERE kind='receipt' AND server_id=? AND remembered=1",
            (expires, digest(token)),
        )
