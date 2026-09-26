"""Ensure the site's favicon reference points at the supplied square PNG."""

import struct
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_favicon_is_a_packaged_square_png():
    class Icons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.icons = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "link" and attributes.get("rel") == "icon":
                self.icons.append(attributes)

    parser = Icons()
    parser.feed((ROOT / "frontend/index.html").read_text())
    assert parser.icons == [
        {"rel": "icon", "type": "image/png", "sizes": "32x32", "href": "/favicon.png"}
    ]
    data = (ROOT / "frontend/public/favicon.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    assert struct.unpack(">II", data[16:24]) == (32, 32)
