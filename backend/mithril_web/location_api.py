"""Location game routes for the website: the guessing map, solo runs, panoramas and guests.

A signed-in player is their linked Minecraft account. Everyone else plays as a guest: a random
token in a cookie, of which only a hash is kept, so a guest is never more than this browser.
"""

import hashlib
import re
import secrets
import time
from typing import Annotated, Literal

from fastapi import HTTPException, Path, Query, Request, Response
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


class Challenge(Body):
    name: Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,16}$")]


class Join(Body):
    code: Annotated[str, Field(pattern=r"^[A-Za-z0-9]{6}$")]


DuelId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{22}$")]
PendingId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{12}$")]


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
    register_world(app)
    register_player(app, browser, players)
    register_solo(app, browser, players)
    register_duels(app, browser, players)


def register_world(app):
    """The guessing map, public and cached by revision."""

    @app.get("/api/v1/games/locations/world")
    def world():
        current = app.state.locations.world
        if not current:
            raise HTTPException(503, "The game is getting ready. Try again in a moment.")
        return {
            "version": 1,
            **current.describe(),
            "image": f"/api/v1/games/locations/world/{current.revision}.png",
        }

    @app.get("/api/v1/games/locations/world/{revision}.png")
    def world_image(revision: Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]):
        current = app.state.locations.world
        if not current or current.revision != revision:
            raise HTTPException(404, "This map has been replaced")
        return Response(
            current.png,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400, immutable"},
        )


def register_player(app, browser, players):
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
        if not who["uuid"]:
            return {
                "version": 1,
                "kind": "guest",
                "name": who["name"],
                "solo": None,
                "rating": None,
            }
        return {
            "version": 1,
            "kind": "linked",
            "name": who["name"],
            "solo": app.state.locations.best(who["uuid"]),
            "rating": app.state.duels.standing(who["uuid"]),
        }

    @app.get("/api/v1/games/locations/leaderboard")
    def leaderboard(request: Request):
        if "origin" in request.headers:
            browser(request)
        try:
            uuid = players.identify(request)["uuid"]
        except HTTPException as error:
            if error.status_code != 401:
                raise
            uuid = None
        return app.state.duels.leaderboard(uuid)

    @app.get("/api/v1/games/locations/duels/history")
    def history(request: Request, offset: Annotated[int, Query(ge=0, le=100_000)] = 0):
        if "origin" in request.headers:
            browser(request)
        who = players.identify(request)
        if not who["uuid"]:
            return {"version": 1, "total": 0, "duels": []}
        return app.state.duels.history(who["uuid"], offset)


def register_solo(app, browser, players):
    def game():
        return app.state.locations

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
        def find():
            try:
                return game().panorama(token)
            except GameError:
                return app.state.duels.panorama(token)

        data = await run_in_threadpool(handle, find)
        return Response(
            data, media_type="image/webp", headers={"Cache-Control": "private, max-age=600"}
        )


def register_duels(app, browser, players):
    """Duels run on the event loop, so these routes are async and never block it for long."""

    def duels():
        return app.state.duels

    def site(request):
        browser(request)
        return players.identify(request)

    def reading(request):
        if "origin" in request.headers:
            browser(request)
        return players.identify(request)

    @app.get("/api/v1/games/locations/duels/inbox")
    async def inbox(request: Request, response: Response, after: Annotated[int, Query(ge=-1)] = -1):
        """Incoming and outgoing challenges and the player's live duel; held until it changes."""
        if "origin" in request.headers:
            browser(request)
        who = players.identify(request, response)
        return await duels().wait_inbox(who, after)

    @app.post("/api/v1/games/locations/duels/challenge")
    async def challenge(body: Challenge, request: Request):
        who = site(request)
        return handle(lambda: duels().challenge(who, body.name))

    @app.post("/api/v1/games/locations/duels/invite")
    async def invite(body: Body, request: Request, response: Response):
        browser(request)
        who = players.identify(request, response)
        return handle(lambda: duels().invite(who))

    @app.post("/api/v1/games/locations/duels/join")
    async def join(body: Join, request: Request, response: Response):
        browser(request)
        who = players.identify(request, response)
        return handle(lambda: duels().join(body.code, who))

    @app.post("/api/v1/games/locations/duels/challenges/{challenge_id}/accept")
    async def accept(challenge_id: PendingId, body: Body, request: Request):
        who = site(request)
        return handle(lambda: duels().accept(challenge_id, who))

    @app.post("/api/v1/games/locations/duels/challenges/{challenge_id}/decline")
    async def decline(challenge_id: PendingId, body: Body, request: Request):
        who = site(request)
        return duels().decline(challenge_id, who)

    @app.get("/api/v1/games/locations/duels/{duel_id}")
    async def duel_state(
        duel_id: DuelId, request: Request, after: Annotated[int, Query(ge=-1)] = -1
    ):
        """The duel from this player's side, held until something changes."""
        who = reading(request)
        try:
            return await duels().wait_state(duel_id, who, after)
        except GameError as error:
            raise HTTPException(error.status, error.detail) from None

    @app.post("/api/v1/games/locations/duels/{duel_id}/ready")
    async def duel_ready(duel_id: DuelId, body: Step, request: Request):
        who = site(request)
        return handle(lambda: duels().ready(duel_id, who, body.round))

    @app.post("/api/v1/games/locations/duels/{duel_id}/guess")
    async def duel_guess(duel_id: DuelId, body: Pin, request: Request):
        who = site(request)
        return handle(lambda: duels().guess(duel_id, who, body.round, body.x, body.z))

    @app.post("/api/v1/games/locations/duels/{duel_id}/leave")
    async def duel_leave(duel_id: DuelId, body: Body, request: Request):
        who = site(request)
        return handle(lambda: duels().leave(duel_id, who))

    @app.post("/api/v1/games/locations/duels/{duel_id}/rematch")
    async def duel_rematch(duel_id: DuelId, body: Body, request: Request):
        who = site(request)
        return handle(lambda: duels().rematch(duel_id, who))
