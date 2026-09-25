"""Single-use Minecraft proofs and opaque browser sessions. No game tokens received."""

import hashlib
import http.client
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import HTTPException

COOKIE = "__Host-mithril_session"
DAY = 86400


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
        self.db.execute("""CREATE TABLE IF NOT EXISTS auth (
            token TEXT PRIMARY KEY, kind TEXT NOT NULL, uuid TEXT NOT NULL, name TEXT NOT NULL,
            expires REAL NOT NULL, server_id TEXT, remembered INTEGER NOT NULL DEFAULT 0)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS auth_expiry ON auth(expires)")
        self.db.commit()

    def close(self):
        self.db.close()

    def cleanup(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth WHERE expires <= ?", (self.clock(),))

    def issue(self, kind, uuid, name, seconds, server_id=None, remembered=False):
        token = secrets.token_urlsafe(32)
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth WHERE expires <= ?", (self.clock(),))
            count = self.db.execute("SELECT COUNT(*) FROM auth WHERE kind=?", (kind,)).fetchone()[0]
            if count >= (100000 if kind == "session" else 1000):
                raise HTTPException(503, "Please try again later")
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
            return dict(row) if row and row["expires"] > self.clock() else None

    def revoke(self, token):
        with self.lock, self.db:
            self.db.execute("DELETE FROM auth WHERE token=? AND kind='session'", (digest(token),))
            self.db.execute(
                "DELETE FROM auth WHERE kind='receipt' AND server_id=? AND remembered=1",
                (digest(token),),
            )

    def confirm_receipts(self, link_token, session_token):
        with self.lock, self.db:
            session = self.db.execute(
                "SELECT expires FROM auth WHERE token=? AND kind='session'",
                (digest(session_token),),
            ).fetchone()
            self.db.execute(
                "UPDATE auth SET server_id=?, expires=?, remembered=1 "
                "WHERE kind='receipt' AND server_id=? AND remembered=0 AND expires>?",
                (digest(session_token), session["expires"], digest(link_token), self.clock()),
            )

    def receipt_status(self, token):
        row = self.get(token, "receipt")
        if not row:
            return {"version": 1, "status": "expired"}
        if not row["remembered"]:
            return {"version": 1, "status": "pending"}
        with self.lock:
            session = self.db.execute(
                "SELECT uuid, name FROM auth WHERE token=? AND kind='session' AND expires>?",
                (row["server_id"], self.clock()),
            ).fetchone()
        if not session:
            return {"version": 1, "status": "expired"}
        return {"version": 1, "status": "linked", "user": dict(session)}

    def renew(self, token):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE auth SET expires=? WHERE token=? AND kind='session'",
                (self.clock() + 30 * DAY, digest(token)),
            )
            self.db.execute(
                "UPDATE auth SET expires=? WHERE kind='receipt' AND server_id=? AND remembered=1",
                (self.clock() + 30 * DAY, digest(token)),
            )
