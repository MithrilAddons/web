"""Read-only, authenticated Discord metadata; never mount on the public application."""

import secrets
import time

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from .leaderboards import snapshot


def summary(finder, stats, release):
    floors = {floor: {"open_parties": 0, "looking": 0} for floor in ("F7", "M7")}
    for party in finder.parties.values():
        if not party.paused and not party.completed and party.open_roles():
            floors[party.floor]["open_parties"] += 1
    for player in finder.players.values():
        if player.looking:
            floors[player.looking["floor"]]["looking"] += 1
    recent = [outcome for outcome in stats.outcomes if outcome[0] > stats.clock() - 300]
    if not recent:
        hypixel = "unknown"
    elif not recent[-1][1]:
        hypixel = "failing"
    elif any(not ok or duration >= 2 for _, ok, duration in recent):
        hypixel = "slow"
    else:
        hypixel = "ok"
    return {
        "version": 1,
        "status": "ok",
        "checked_at": time.time(),
        "floors": floors,
        "hypixel": hypixel,
        "latest_version": (release.get("release") or {}).get("version"),
    }


def create_internal(public_app, secret):
    if len(secret) != 64 or any(c not in "0123456789abcdef" for c in secret):
        raise ValueError("Internal secret must be 32 random bytes encoded as lowercase hex")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        # Check the actual peer; this listener never trusts forwarded headers.
        authorized = (
            request.client is not None
            and request.client.host == "127.0.0.1"
            and secrets.compare_digest(
                request.headers.get("authorization", "").encode(), f"Bearer {secret}".encode()
            )
        )
        if not authorized:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if request.method != "GET" or request.headers.get("content-length", "0") != "0":
            return JSONResponse({"detail": "Read-only API"}, status_code=405)
        if request.headers.get("transfer-encoding"):
            return JSONResponse({"detail": "Body not allowed"}, status_code=400)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/internal/v1/summary")
    async def get_summary():
        # Event-loop snapshot only; no network or disk work while reading Finder.
        state = public_app.state
        return summary(state.finder, state.finder_stats, state.releases.value)

    @app.get("/internal/v1/releases")
    def get_releases():
        return public_app.state.releases.discord()

    @app.get("/internal/v1/leaderboards")
    def get_leaderboards():
        state = public_app.state
        return snapshot(state.records, state.auth)

    return app
