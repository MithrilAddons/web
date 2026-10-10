"""Offline visual harness: synthetic account/skin, loopback only, no auth or Mojang calls."""

import base64
import json
import struct
import zlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DIST = Path(__file__).resolve().parents[1] / "frontend/dist"
CARD = DIST.parents[1] / "contracts/player-card-v1.json"


CLEAR = (0, 0, 0, 0)
HAIR = (65, 47, 40, 255)
FACE = (190, 155, 125, 255)
EYE = (30, 45, 60, 255)
TROUSERS = (60, 65, 90, 255)
SHIRT = (110, 115, 210, 255)


def skin_pixel(x, y):
    """One pixel of the synthetic 64x64 skin: head, then body and arms, then legs."""
    if y < 16:
        if x >= 32:
            return CLEAR
        if y < 8:
            return HAIR
        return EYE if y == 11 and x in (10, 13) else FACE
    if y < 32:
        return TROUSERS if x < 16 else SHIRT
    if y < 48:
        return CLEAR
    if 16 <= x < 32:
        return TROUSERS
    return SHIRT if 32 <= x < 48 else CLEAR


def synthetic_skin():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    rows = bytearray()
    for y in range(64):
        rows.append(0)
        for x in range(64):
            rows.extend(skin_pixel(x, y))
    image = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 6, 0, 0, 0))
    image += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(image).decode()


class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/api/v1/party/skin/"):
            path = "/api/v1/auth/skin"
        routes = {
            "/api/v1/health": {"status": "ok", "service": "mithril-web", "api_version": 1},
            "/api/v1/auth/session": {
                "authenticated": True,
                "user": {"name": "TestPlayer", "uuid": "0123456789abcdef0123456789abcdef"},
            },
            "/api/v1/auth/skin": {"image": synthetic_skin(), "model": "default"},
            "/api/v1/auth/player-card": json.loads(CARD.read_text(encoding="utf-8")),
        }
        if path in routes:
            data = json.dumps(routes[path]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path in (
            "/",
            "/party-finder",
            "/cookies",
            "/link",
            "/profile",
            "/account",
            "/slayer-profits",
        ):
            self.path = "/index.html"
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        """Link-screen preview only; these fixed synthetic credentials never authenticate."""
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096 or path not in ("/api/v1/auth/preview", "/api/v1/auth/complete"):
            self.send_error(400)
            return
        body = json.loads(self.rfile.read(length))
        valid = body.get("token") in ("ABCDEFGH", "a" * 43)
        user = {"name": "TestPlayer", "uuid": "0123456789abcdef0123456789abcdef"}
        result = user if path.endswith("preview") else {"authenticated": True, "user": user}
        data = json.dumps(result if valid else {"detail": "Synthetic code only"}).encode()
        self.send_response(200 if valid else 410)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; connect-src 'self'",
        )
        # JSON stays JSON: browsers must not sniff a response into something renderable.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    if not (DIST / "index.html").is_file():
        raise SystemExit("Run npm run build first.")
    print("Synthetic preview only: http://127.0.0.1:8770/party-finder — Ctrl+C to stop", flush=True)
    with ThreadingHTTPServer(("127.0.0.1", 8770), Preview) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
