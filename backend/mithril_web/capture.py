"""Location-game captures: panoramas and island maps submitted from the capture mod for review.

Rows live in records.sqlite3 so account erasure removes them with the PBs; images are
re-encoded on arrival (dropping all metadata) and kept under random IDs in the data folder.
"""

import io
import math
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

STATUSES = ("uploading", "submitted", "approved", "changes_requested", "rejected", "retired")
DECISIONS = {
    "approve": "approved",
    "changes": "changes_requested",
    "reject": "rejected",
    "retire": "retired",
}
REFUSED_ISLANDS = {"dynamic", "garden", "dungeon", "kuudra"}
DAILY_LIMIT = 200
NEARBY = 10.0
MAX_MAP = 4096
FACES = 6
ALL_FACES = (1 << FACES) - 1
REJECTED_KEPT = 30 * 86400
IMAGE_FAILURES = (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError)


class CaptureError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status, self.detail = status, detail


def new_id():
    return secrets.token_urlsafe(16)[:22]


def faces_list(mask):
    return [n for n in range(FACES) if mask & (1 << n)]


def reencode(data, width=None, height=None):
    """PNG bytes checked for size and re-saved, so nothing but pixels survives."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise CaptureError(422, "Images must be PNG")
            if (width and image.width != width) or (height and image.height != height):
                raise CaptureError(422, f"The image must be {width}×{height} pixels")
            mode = "RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB"
            output = io.BytesIO()
            image.convert(mode).save(output, "PNG")
            return output.getvalue()
    except IMAGE_FAILURES as error:
        raise CaptureError(422, "That isn't a readable PNG image") from error


class CaptureStore:
    """records.lock guards the rows; files are written before the row that points at them."""

    def __init__(self, records, folder: Path):
        self.records, self.db, self.lock, self.clock = (
            records,
            records.db,
            records.lock,
            records.clock,
        )
        self.folder = folder
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS capture_locations (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL, uuid TEXT, name TEXT,
                island TEXT NOT NULL, island_name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
                z REAL NOT NULL, captured_at INTEGER NOT NULL, note TEXT NOT NULL,
                face_size INTEGER NOT NULL, faces INTEGER NOT NULL, status TEXT NOT NULL,
                reviewer_note TEXT, reviewer TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                UNIQUE (uuid, client_id));
            CREATE INDEX IF NOT EXISTS capture_location_island ON capture_locations(island, status);
            CREATE TABLE IF NOT EXISTS capture_maps (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL, uuid TEXT, name TEXT,
                island TEXT NOT NULL, island_name TEXT NOT NULL, min_x INTEGER NOT NULL,
                min_z INTEGER NOT NULL, max_x INTEGER NOT NULL, max_z INTEGER NOT NULL,
                status TEXT NOT NULL, reviewer_note TEXT, reviewer TEXT, created REAL NOT NULL,
                updated REAL NOT NULL, UNIQUE (uuid, client_id));
            CREATE TABLE IF NOT EXISTS capture_code_use (code TEXT PRIMARY KEY, used REAL NOT NULL);
        """)
        self.db.commit()

    # Paths

    def _location_dir(self, location_id):
        return self.folder / "locations" / location_id

    def face_path(self, location_id, face):
        return self._location_dir(location_id) / f"{face}.png"

    def map_path(self, map_id):
        return self.folder / "maps" / f"{map_id}.png"

    @staticmethod
    def _write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    # Capturer side

    def _today_count(self, uuid):
        start = datetime.fromtimestamp(self.clock(), UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        since = start.timestamp()
        return sum(
            self.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE uuid=? AND created>=?", (uuid, since)
            ).fetchone()[0]
            for table in ("capture_locations", "capture_maps")
        )

    def _check_island(self, island):
        if island in REFUSED_ISLANDS:
            raise CaptureError(422, "Private islands, gardens and instances can't be captured")

    def used(self, code):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO capture_code_use VALUES (?, ?)", (code, self.clock())
            )

    def last_used(self, codes):
        if not codes:
            return {}
        with self.lock:
            return {
                row["code"]: row["used"]
                for row in self.db.execute(
                    f"SELECT code, used FROM capture_code_use WHERE code IN "
                    f"({','.join('?' * len(codes))})",
                    list(codes),
                )
            }

    def nearby(self, island, x, z):
        with self.lock:
            rows = self.db.execute(
                "SELECT x, z, status FROM capture_locations WHERE island=? "
                "AND status IN ('submitted', 'approved') AND x BETWEEN ? AND ? "
                "AND z BETWEEN ? AND ?",
                (island, x - NEARBY, x + NEARBY, z - NEARBY, z + NEARBY),
            ).fetchall()
        found = []
        for row in rows:
            distance = math.hypot(row["x"] - x, row["z"] - z)
            if distance <= NEARBY:
                found.append(
                    {
                        "x": row["x"],
                        "z": row["z"],
                        "distance": round(distance, 1),
                        "status": "live" if row["status"] == "approved" else "pending",
                    }
                )
        return sorted(found, key=lambda entry: entry["distance"])

    def create_location(self, user, body):
        self._check_island(body.island)
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT id, status, faces FROM capture_locations WHERE uuid=? AND client_id=?",
                (user["uuid"], body.client_id),
            ).fetchone()
            if row:
                return {
                    "version": 1,
                    "id": row["id"],
                    "status": row["status"],
                    "faces": faces_list(row["faces"]),
                }
            if self._today_count(user["uuid"]) >= DAILY_LIMIT:
                raise CaptureError(429, f"Daily limit of {DAILY_LIMIT} submissions reached")
            location_id, now = new_id(), self.clock()
            self.db.execute(
                "INSERT INTO capture_locations VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,0,'uploading',NULL,NULL,?,?)",
                (
                    location_id,
                    body.client_id,
                    user["uuid"],
                    user["name"],
                    body.island,
                    body.island_name,
                    body.x,
                    body.y,
                    body.z,
                    body.captured_at,
                    body.note,
                    body.face_size,
                    now,
                    now,
                ),
            )
        return {"version": 1, "id": location_id, "status": "uploading", "faces": []}

    def _own_location(self, uuid, location_id):
        row = self.db.execute(
            "SELECT * FROM capture_locations WHERE id=? AND uuid=?", (location_id, uuid)
        ).fetchone()
        if not row:
            raise CaptureError(404, "Unknown capture")
        return row

    def upload_face(self, uuid, location_id, face, data):
        with self.lock:
            row = self._own_location(uuid, location_id)
        if row["status"] != "uploading":
            raise CaptureError(409, "This capture was already submitted")
        size = row["face_size"]
        png = reencode(data, size, size)
        self._write(self.face_path(location_id, face), png)
        with self.lock, self.db:
            self.db.execute(
                "UPDATE capture_locations SET faces=faces | ?, updated=? WHERE id=?",
                (1 << face, self.clock(), location_id),
            )
            mask = self._own_location(uuid, location_id)["faces"]
        return {"version": 1, "faces": faces_list(mask)}

    def finish_location(self, uuid, location_id):
        with self.lock, self.db:
            row = self._own_location(uuid, location_id)
            if row["status"] == "uploading":
                if row["faces"] != ALL_FACES:
                    raise CaptureError(409, "Some panorama faces haven't been uploaded yet")
                self.db.execute(
                    "UPDATE capture_locations SET status='submitted', updated=? WHERE id=?",
                    (self.clock(), location_id),
                )
                return {"version": 1, "status": "submitted"}
            return {"version": 1, "status": row["status"]}

    def create_map(self, user, body):
        self._check_island(body.island)
        width, height = body.max_x - body.min_x + 1, body.max_z - body.min_z + 1
        if not (1 <= width <= MAX_MAP and 1 <= height <= MAX_MAP):
            raise CaptureError(422, f"Maps can be at most {MAX_MAP} blocks across")
        with self.lock, self.db:
            row = self.db.execute(
                "SELECT id, status FROM capture_maps WHERE uuid=? AND client_id=?",
                (user["uuid"], body.client_id),
            ).fetchone()
            if row:
                return {"version": 1, "id": row["id"], "status": row["status"]}
            if self._today_count(user["uuid"]) >= DAILY_LIMIT:
                raise CaptureError(429, f"Daily limit of {DAILY_LIMIT} submissions reached")
            map_id, now = new_id(), self.clock()
            self.db.execute(
                "INSERT INTO capture_maps VALUES (?,?,?,?,?,?,?,?,?,?,'uploading',NULL,NULL,?,?)",
                (
                    map_id,
                    body.client_id,
                    user["uuid"],
                    user["name"],
                    body.island,
                    body.island_name,
                    body.min_x,
                    body.min_z,
                    body.max_x,
                    body.max_z,
                    now,
                    now,
                ),
            )
        return {"version": 1, "id": map_id, "status": "uploading"}

    def upload_map(self, uuid, map_id, data):
        with self.lock:
            row = self.db.execute(
                "SELECT * FROM capture_maps WHERE id=? AND uuid=?", (map_id, uuid)
            ).fetchone()
        if not row:
            raise CaptureError(404, "Unknown map")
        if row["status"] != "uploading":
            raise CaptureError(409, "This map was already submitted")
        png = reencode(data, row["max_x"] - row["min_x"] + 1, row["max_z"] - row["min_z"] + 1)
        self._write(self.map_path(map_id), png)
        with self.lock, self.db:
            now = self.clock()
            # A newer map replaces the same capturer's unreviewed one for that island.
            self.db.execute(
                "UPDATE capture_maps SET status='rejected', reviewer_note='Replaced by a newer "
                "map', updated=? WHERE uuid=? AND island=? AND status='submitted' AND id!=?",
                (now, uuid, row["island"], map_id),
            )
            self.db.execute(
                "UPDATE capture_maps SET status='submitted', updated=? WHERE id=?", (now, map_id)
            )
        return {"version": 1, "status": "submitted"}

    def submissions(self, uuid):
        def rows(table):
            return [
                {
                    "id": row["id"],
                    "client_id": row["client_id"],
                    "island": row["island"],
                    "status": row["status"],
                    "reviewer_note": row["reviewer_note"],
                    "updated": int(row["updated"]),
                }
                for row in self.db.execute(
                    f"SELECT * FROM {table} WHERE uuid=? ORDER BY updated DESC LIMIT 500",
                    (uuid,),
                )
            ]

        with self.lock:
            return {
                "version": 1,
                "locations": rows("capture_locations"),
                "maps": rows("capture_maps"),
            }

    # Review side

    def review(self, kind, status, offset):
        table = "capture_locations" if kind == "locations" else "capture_maps"
        with self.lock:
            where, params = ("", []) if status == "all" else ("WHERE status=?", [status])
            total = self.db.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()[0]
            rows = [
                {key: row[key] for key in row.keys() if key != "uuid"}
                for row in self.db.execute(
                    f"SELECT * FROM {table} {where} ORDER BY updated DESC LIMIT 25 OFFSET ?",
                    [*params, offset],
                )
            ]
            current = {
                row["island"]: row["id"]
                for row in self.db.execute(
                    "SELECT island, id FROM capture_maps m WHERE status='approved' AND updated="
                    "(SELECT MAX(updated) FROM capture_maps WHERE island=m.island "
                    "AND status='approved')"
                )
            }
            maps = {
                row["id"]: {key: row[key] for key in ("min_x", "min_z", "max_x", "max_z")}
                for map_id in current.values()
                for row in self.db.execute("SELECT * FROM capture_maps WHERE id=?", (map_id,))
            }
        return {
            "version": 1,
            "total": total,
            "items": rows,
            "current_maps": {
                island: {"id": map_id, **maps[map_id]} for island, map_id in current.items()
            },
        }

    def decide(self, actor, kind, item_id, decision, note):
        table = "capture_locations" if kind == "locations" else "capture_maps"
        if decision in ("changes", "reject") and not note.strip():
            raise CaptureError(422, "Tell the capturer what to change")
        with self.lock, self.db:
            row = self.db.execute(f"SELECT status FROM {table} WHERE id=?", (item_id,)).fetchone()
            if not row:
                raise CaptureError(404, "Unknown submission")
            if row["status"] == "uploading":
                raise CaptureError(409, "This submission is still uploading")
            # Retiring takes a live location out of the game, e.g. after Hypixel rebuilds it.
            if decision == "retire" and (kind != "locations" or row["status"] != "approved"):
                raise CaptureError(409, "Only live locations can be retired")
            self.db.execute(
                f"UPDATE {table} SET status=?, reviewer_note=?, reviewer=?, updated=? WHERE id=?",
                (DECISIONS[decision], note.strip() or None, actor, self.clock(), item_id),
            )

    def image(self, kind, item_id, face=None):
        path = self.face_path(item_id, face) if kind == "locations" else self.map_path(item_id)
        with self.lock:
            table = "capture_locations" if kind == "locations" else "capture_maps"
            known = self.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone()
        if not known or not path.is_file():
            raise CaptureError(404, "Image unavailable")
        return path.read_bytes()

    # Upkeep

    def cleanup(self):
        """Deletes rejected submissions after 30 days and files no row points at any more."""
        with self.lock, self.db:
            cutoff = self.clock() - REJECTED_KEPT
            for table in ("capture_locations", "capture_maps"):
                self.db.execute(
                    f"DELETE FROM {table} WHERE status='rejected' AND updated<?", (cutoff,)
                )
            locations = {r[0] for r in self.db.execute("SELECT id FROM capture_locations")}
            maps = {r[0] for r in self.db.execute("SELECT id FROM capture_maps")}
        for folder in (self.folder / "locations").glob("*"):
            if folder.name not in locations:
                shutil.rmtree(folder, ignore_errors=True)
        for path in (self.folder / "maps").glob("*.png"):
            if path.stem not in maps:
                path.unlink(missing_ok=True)


def erase_captures(db, uuid):
    """Account erasure: unreviewed work goes, approved locations and maps stay unattributed."""
    for table in ("capture_locations", "capture_maps"):
        db.execute(f"DELETE FROM {table} WHERE uuid=? AND status!='approved'", (uuid,))
        db.execute(f"UPDATE {table} SET uuid=NULL, name=NULL WHERE uuid=?", (uuid,))
        db.execute(f"UPDATE {table} SET reviewer=NULL WHERE reviewer=?", (uuid,))
