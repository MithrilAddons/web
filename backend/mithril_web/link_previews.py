"""Server-rendered share metadata; crawlers do not execute the React application."""

import re
from html import escape
from pathlib import Path

from fastapi import HTTPException, Response
from fastapi.responses import HTMLResponse

from .run_maps import public_record
from .run_preview import render_preview, run_time

INDEX = Path(__file__).resolve().parents[2] / "frontend/dist/index.html"
ORIGIN = "https://mithril.foo"


def read_run(app, record_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", record_id):
        raise HTTPException(404, "Record unavailable")
    return public_record(app.state.records, record_id)


def metadata(record_id, run):
    title = "Run unavailable · Mithril"
    description = "This run is unavailable."
    image = None
    if run:
        record = run["record"]
        name = record["name"] or record["uuid"]
        title = f"{record['floor']} solo clear · {run_time(record['ticks'])} · {name}"
        description = "View this solo-clear record on Mithril."
        if run["map"]:
            description = "Explore the dungeon map and room secrets captured at 300 score."
            image = f"{ORIGIN}/api/v1/records/solo/{record_id}/preview.png"
    tags = {
        "og:site_name": "Mithril",
        "og:type": "website",
        "og:title": title,
        "og:description": description,
        "og:url": f"{ORIGIN}/runs/{record_id}",
    }
    if image:
        tags.update(
            {
                "og:image": image,
                "og:image:type": "image/png",
                "og:image:width": "1200",
                "og:image:height": "630",
                "og:image:alt": f"Dungeon map at 300 score: {title}",
            }
        )
    lines = [f"<title>{escape(title)}</title>"]
    lines += [
        f'<meta property="{key}" content="{escape(value, quote=True)}" />'
        for key, value in tags.items()
    ]
    lines += [
        f'<meta name="description" content="{escape(description, quote=True)}" />',
        f'<meta name="twitter:card" content="{"summary_large_image" if image else "summary"}" />',
    ]
    return "\n".join(lines)


def register_previews(app):
    @app.api_route("/runs/{record_id}", methods=["GET", "HEAD"], response_class=HTMLResponse)
    def run_page(record_id: str):
        status = 200
        try:
            run = read_run(app, record_id)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            run, status = None, 404
        # The built SPA still hydrates normally; only its share metadata is replaced.
        try:
            template = INDEX.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise HTTPException(503, "Frontend build unavailable") from error
        html = re.sub(
            r"<!-- share:start -->.*?<!-- share:end -->",
            lambda _: metadata(record_id, run),
            template,
            flags=re.S,
        )
        return HTMLResponse(html, status_code=status)

    @app.api_route("/api/v1/records/solo/{record_id}/preview.png", methods=["GET", "HEAD"])
    def run_image(record_id: str):
        run = read_run(app, record_id)
        if run["map"] is None:
            raise HTTPException(404, "Map unavailable")
        return Response(render_preview(run), media_type="image/png")
