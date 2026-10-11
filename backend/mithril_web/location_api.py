"""Location game routes for the website: the guessing map, solo runs, panoramas and guests.

A signed-in player is their linked Minecraft account. Everyone else plays as a guest: a random
token in a cookie, of which only a hash is kept, so a guest is never more than this browser.
"""

import hashlib
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import HTTPException, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE, DAY, AuthAttempts
from .location_game import GameError

GUEST_COOKIE = "mithril_guest"
GUEST_PATTERN = r"[A-Za-z0-9_-]{43}"
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{22}$")]
Coordinate = Annotated[float, Field(ge=-100_000, le=100_000)]
Number = Annotated[int, Field(ge=1, le=20)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]


class Step(Body):
    round: Number


class Pin(Step):
    x: Coordinate
    z: Coordinate


def guest_name(player):
    return f"Guest #{int(player[2:6], 16) % 10000:04}"


def handle(action):
    try:
        return action()
    except GameError as error:
        raise HTTPException(error.status, error.detail) from None


class Players:
    """Who is playing: the linked account behind the session cookie, or this browser's guest."""

    def __init__(self, app, browser, clock):
        self.app, self.browser = app, browser
        self.new_guests = AuthAttempts(5, 300, clock=clock)

    def identify(self, request, response=None):
        host = request.client.host if request.client else None
        row = self.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if row:
            self.app.state.moderation.check(row["uuid"], host)
            return {"player": "u:" + row["uuid"], "uuid": row["uuid"], "name": row["name"]}
        # Network bans still apply to guests.
        self.app.state.moderation.check(None, host)
        token = request.cookies.get(GUEST_COOKIE, "")
        if not re.fullmatch(GUEST_PATTERN, token):
            if response is None:
                raise HTTPException(401, "Start a game first")
            self.new_guests.check(host or "unknown")
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                GUEST_COOKIE,
                token,
                max_age=30 * DAY,
                secure=True,
                httponly=True,
                samesite="strict",
                path="/api/v1/games/locations",
            )
        player = "g:" + hashlib.sha256(token.encode()).hexdigest()[:32]
        return {"player": player, "uuid": None, "name": guest_name(player)}


def register_locations(app, browser, clock=time.monotonic):
    players = Players(app, browser, clock)

    def game():
        return app.state.locations

    @app.get("/api/v1/games/locations/world")
    def world():
        current = game().world
        if not current:
            raise HTTPException(503, "The game is getting ready. Try again in a moment.")
        return {
            "version": 1,
            **current.describe(),
            "image": f"/api/v1/games/locations/world/{current.revision}.png",
        }

    @app.get("/api/v1/games/locations/world/{revision}.png")
    def world_image(revision: Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]):
        current = game().world
        if not current or current.revision != revision:
            raise HTTPException(404, "This map has been replaced")
        return Response(
            current.png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )

    @app.get("/api/v1/games/locations/me")
    def me(request: Request):
        if "origin" in request.headers:
            browser(request)
        try:
            who = players.identify(request)
        except HTTPException as error:
            if error.status_code != 401:
                raise
            return {"version": 1, "kind": "guest", "name": None, "solo": None}
        solo = game().best(who["uuid"]) if who["uuid"] else None
        kind = "linked" if who["uuid"] else "guest"
        return {"version": 1, "kind": kind, "name": who["name"], "solo": solo}

    @app.post("/api/v1/games/locations/solo")
    def start(body: Body, request: Request, response: Response):
        browser(request)
        who = players.identify(request, response)
        return handle(lambda: game().start(who["player"], who["uuid"]))

    @app.get("/api/v1/games/locations/solo/{run_id}")
    def state(run_id: RunId, request: Request):
        if "origin" in request.headers:
            browser(request)
        who = players.identify(request)
        return handle(lambda: game().state(run_id, who["player"]))

    @app.post("/api/v1/games/locations/solo/{run_id}/ready")
    def ready(run_id: RunId, body: Step, request: Request):
        browser(request)
        who = players.identify(request)
        return handle(lambda: game().ready(run_id, who["player"], body.round))

    @app.post("/api/v1/games/locations/solo/{run_id}/guess")
    def guess(run_id: RunId, body: Pin, request: Request):
        browser(request)
        who = players.identify(request)
        return handle(lambda: game().guess(run_id, who["player"], body.round, body.x, body.z))

    @app.post("/api/v1/games/locations/solo/{run_id}/next")
    def next_round(run_id: RunId, body: Step, request: Request):
        browser(request)
        who = players.identify(request)
        return handle(lambda: game().next(run_id, who["player"], body.round))

    @app.get("/api/v1/games/locations/panorama/{token}.webp")
    async def panorama(token: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{24}$")]):
        # The token is the round's own; the image's name never repeats between rounds.
        data = await run_in_threadpool(handle, lambda: game().panorama(token))
        return Response(
            data, media_type="image/webp", headers={"Cache-Control": "private, max-age=600"}
        )
