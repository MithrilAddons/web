"""Owner-only Curator review: answer queue, allow and block lists, popularity cut-off."""

from typing import Annotated, Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import COOKIE

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
