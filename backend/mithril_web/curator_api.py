"""Owner-only Curator review: answer queue, allow and block lists, popularity cut-off."""

from typing import Annotated, Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import COOKIE
from .curator_game import GameError

ItemId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_:;.\-]{1,128}$")]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class CuratorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]


class ListChange(CuratorBody):
    item: ItemId
    list: Literal["allow", "block"] | None


class DayChange(CuratorBody):
    day: Day
    item: ItemId | None


class Guess(CuratorBody):
    day: Day
    item: ItemId


class Settings(CuratorBody):
    sales_cutoff: int = Field(ge=0, le=1_000_000)


def register_curator(app, browser):
    def owner(request):
        row = app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in with your linked Minecraft account")
        app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
        if app.state.moderation.role(row["uuid"]) != "owner":
            raise HTTPException(403, "Owner access required")
        return row["uuid"]

    def change(request, action):
        browser(request)
        actor = owner(request)
        try:
            action(actor)
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None
        return {"version": 1}

    @app.get("/api/v1/moderation/curator")
    def overview(request: Request):
        owner(request)
        return app.state.curator.overview()

    @app.get("/api/v1/moderation/curator/items")
    def items(
        request: Request,
        group: Literal["pool", "admin", "new", "allowed", "blocked", "all"] = "pool",
        query: Annotated[str, Query(max_length=64)] = "",
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ):
        owner(request)
        return app.state.curator.review(group, query, offset)

    @app.post("/api/v1/moderation/curator/list")
    def set_list(body: ListChange, request: Request):
        return change(
            request, lambda actor: app.state.curator.set_list(body.item, body.list, actor)
        )

    @app.post("/api/v1/moderation/curator/day")
    def set_day(body: DayChange, request: Request):
        curator = app.state.curator
        return change(
            request,
            lambda actor: (
                curator.schedule(body.day, body.item, actor)
                if body.item
                else curator.reroll(body.day, actor)
            ),
        )

    @app.post("/api/v1/moderation/curator/settings")
    def settings(body: Settings, request: Request):
        return change(request, lambda _: app.state.curator.set_cutoff(body.sales_cutoff))

    @app.post("/api/v1/moderation/curator/reviewed")
    def reviewed(body: CuratorBody, request: Request):
        return change(request, lambda _: app.state.curator.mark_reviewed())


def register_curator_game(app, device_user):
    """Mod routes for playing Curator; a linked device session identifies the player."""

    def player(request):
        row = device_user(request)
        app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
        return row

    @app.get("/api/v1/games/curator/catalog")
    def catalog(request: Request, version: Annotated[str, Query(max_length=64)] = ""):
        player(request)
        current, items = app.state.curator.guess_list()
        if version and version == current:
            return {"version": 1, "catalog": current, "unchanged": True}
        return {"version": 1, "catalog": current, "items": items}

    @app.get("/api/v1/games/curator/today")
    def today(request: Request):
        return app.state.curator_game.state(player(request)["uuid"])

    @app.post("/api/v1/games/curator/guess")
    def guess(body: Guess, request: Request):
        row = player(request)
        try:
            return app.state.curator_game.guess(row["uuid"], row["name"], body.day, body.item)
        except GameError as error:
            raise HTTPException(error.status, error.detail) from None

    @app.get("/api/v1/games/curator/leaderboard")
    def leaderboard(request: Request):
        return app.state.curator_game.leaderboard(player(request)["uuid"])
