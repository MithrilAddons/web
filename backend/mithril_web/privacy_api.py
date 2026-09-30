"""Self-service erasure remains available to restricted accounts."""

import os
from typing import Literal

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE


class Erase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    scope: Literal["records", "account"]
    confirmation: Literal["DELETE"]


def register_privacy(app, browser, skins, cards, device_user):
    @app.get("/api/v1/privacy")
    def contact():
        operator, email = (
            os.environ.get("MITHRIL_PRIVACY_OPERATOR"),
            os.environ.get("MITHRIL_PRIVACY_EMAIL"),
        )
        if not operator or not email:
            raise HTTPException(503, "Privacy contact is not configured")
        return {"version": 1, "operator": operator, "email": email}

    @app.post("/api/v1/auth/device-erase")
    @app.post("/api/v1/auth/erase")
    async def erase(body: Erase, request: Request, response: Response):
        native = request.url.path.endswith("device-erase")
        if native:
            await run_in_threadpool(device_user, request)
        else:
            browser(request)
        token = request.headers["authorization"][7:] if native else request.cookies.get(COOKIE, "")
        uuid = await run_in_threadpool(
            app.state.privacy.erase, token, body.scope, "device" if native else "session"
        )
        await app.state.records_changed(uuid)
        if body.scope == "account":
            app.state.erase_player(uuid)
            await run_in_threadpool(skins.erase, uuid)
            await run_in_threadpool(cards.erase, uuid)
            response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
        return {"version": 1, "deleted": body.scope}
