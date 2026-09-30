"""Same-origin moderator API; role checks and writes are one database transaction."""

import http.client
import re
from typing import Annotated, Literal

from fastapi import HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE

AccountId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
RecordId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError("A reason is required")
        return value.strip()


class Grant(Action):
    uuid: AccountId
    enabled: bool


class RecordAction(Action):
    record_id: RecordId
    expected_status: Literal["eligible", "invalidated"]
    action: Literal["invalidate", "restore", "correct"]
    real_ms: int | None = Field(default=None, ge=1, le=7_200_000)
    ticks: int | None = Field(default=None, ge=1, le=144_000)

    @model_validator(mode="after")
    def correction_values(self):
        if self.action == "correct":
            if self.real_ms is None or self.ticks is None:
                raise ValueError("Corrected time and ticks are required")
        elif self.real_ms is not None or self.ticks is not None:
            raise ValueError("Only corrections accept time and ticks")
        return self


class Sanction(Action):
    uuid: AccountId
    kind: Literal["ban", "network_ban", "mute"]
    expires: int | None = Field(default=None, ge=1)
    record_ids: list[RecordId] = Field(default_factory=list, max_length=20)
    report_ids: list[RecordId] = Field(default_factory=list, max_length=20)


class CaseAction(Action):
    case_id: RecordId
    action: Literal["revoke", "open_appeal", "close_appeal"]


class ChatAction(Action):
    report_id: RecordId
    action: Literal["hide", "dismiss"]


def register_moderation(app, browser, name_lookup):
    def actor(request):
        row = app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in with your linked Minecraft account")
        app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
        return row["uuid"]

    def read(request, method, *args):
        with app.state.records.lock:
            return getattr(app.state.moderation, method)(actor(request), *args)

    async def write(request, method, *args):
        browser(request)
        return await run_in_threadpool(read, request, method, *args)

    @app.get("/api/v1/moderation/access")
    def access(request: Request):
        return read(request, "home")

    @app.get("/api/v1/moderation/player/{uuid}")
    def player(uuid: AccountId, request: Request):
        return read(request, "inspect", uuid)

    @app.get("/api/v1/moderation/resolve/{name}")
    def resolve(name: str, request: Request):
        read(request, "home")
        if not re.fullmatch(r"\w{1,16}", name, flags=re.ASCII):
            raise HTTPException(422, "Enter a Minecraft username")
        try:
            result = name_lookup(name)
        except (OSError, ValueError, TypeError, http.client.HTTPException):
            raise HTTPException(503, "Name lookup unavailable") from None
        if not result:
            raise HTTPException(404, "Player not found")
        return {"version": 1, "uuid": result[0], "name": result[1]}

    @app.get("/api/v1/moderation/audit")
    def audit(request: Request, before: Annotated[int, Query(ge=1, le=2**63 - 1)] = 2**63 - 1):
        return read(request, "audit", before)

    @app.get("/api/v1/moderation/evidence/{record_id}")
    def evidence(record_id: RecordId, request: Request):
        return read(request, "evidence", record_id)

    @app.get("/api/v1/moderation/case/{case_id}/evidence")
    def case_evidence(case_id: RecordId, request: Request):
        return read(request, "case_evidence", case_id)

    @app.post("/api/v1/moderation/access")
    async def grant(body: Grant, request: Request):
        await write(request, "grant", body.uuid, body.enabled, body.reason)
        return {"version": 1}

    @app.post("/api/v1/moderation/record")
    async def record(body: RecordAction, request: Request):
        uuid = await write(request, "record_action", body)
        await app.state.records_changed(uuid)
        return {"version": 1}

    @app.post("/api/v1/moderation/sanction")
    async def sanction(body: Sanction, request: Request):
        case = await write(request, "sanction", body)
        if body.kind != "mute":
            affected = await run_in_threadpool(app.state.moderation.affected_accounts, case)
            app.state.remove_players(affected)
        return {"version": 1, "case": case}

    @app.post("/api/v1/moderation/case")
    async def case_action(body: CaseAction, request: Request):
        case = await write(request, "case_action", body)
        await run_in_threadpool(app.state.records.cleanup)
        return {"version": 1, "case": case}

    @app.get("/api/v1/moderation/chat")
    def reports(request: Request):
        return app.state.moderation.chat.list(actor(request))

    @app.post("/api/v1/moderation/chat")
    async def review_chat(body: ChatAction, request: Request):
        browser(request)

        def review():
            with app.state.records.lock:
                return app.state.moderation.chat.resolve(
                    actor(request), body.report_id, body.action, body.reason
                )

        party_id, message_id = await run_in_threadpool(review)
        if body.action == "hide":
            app.state.hide_message(party_id, message_id)
        return {"version": 1}
