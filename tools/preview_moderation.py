"""Loopback-only moderation layout preview with fixed synthetic records and no writes."""

import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preview_skin import Preview  # noqa: E402

UUID = "c" * 32


class ModerationPreview(Preview):
    def json(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/moderation", "/privacy", "/account"):
            self.path = "/index.html"
        elif path == "/api/v1/privacy":
            return self.json({"operator": "Synthetic Operator", "email": "privacy@example.invalid"})
        elif path == "/api/v1/moderation/access":
            return self.json({"role": "owner", "moderators": [], "network_bans_available": True})
        elif path.startswith("/api/v1/moderation/resolve/"):
            return self.json({"uuid": UUID, "name": "SyntheticPlayer"})
        elif path.startswith("/api/v1/moderation/player/"):
            return self.json(
                {
                    "uuid": UUID,
                    "records": [
                        {
                            "id": "r" * 43,
                            "floor": "F7",
                            "kind": "solo_clear",
                            "real_ms": 125320,
                            "ticks": 2506,
                            "source": "live",
                            "status": "eligible",
                        }
                    ],
                    "cases": [
                        {
                            "id": "s" * 43,
                            "kind": "mute",
                            "expires": None,
                            "revoked": None,
                            "appeal_open": 0,
                            "reason": "Synthetic case for layout review",
                        }
                    ],
                }
            )
        elif path.startswith("/api/v1/moderation/"):
            return self.json({"entries": [], "reports": []})
        return super().do_GET()


if __name__ == "__main__":
    # Synthetic, read-only loopback preview; no real accounts or credentials are served.
    ThreadingHTTPServer(("127.0.0.1", 8792), ModerationPreview).serve_forever()  # NOSONAR
