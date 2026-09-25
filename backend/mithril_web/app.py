"""Same-origin web API. Authentication does not authorize gameplay records yet."""

import asyncio
import contextlib
import http.client
import os
import re
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import COOKIE, DAY, AuthStore, digest, mojang_profile
from .skins import SkinCache


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Challenge(StrictModel):
    version: Literal[1]
    uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")


class Proof(StrictModel):
    challenge_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class Link(StrictModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class Complete(Link):
    remember: bool


def identity(row):
    return {"uuid": row["uuid"], "name": row["name"]}


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["mithril-web"] = "mithril-web"
    api_version: Literal[1] = 1


def create_app(
    *, database=None, profile_lookup=mojang_profile, clock=None, skin_loader=None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        path = database or Path(os.environ.get("MITHRIL_AUTH_DB", ".local/auth.sqlite3"))
        app.state.auth = AuthStore(Path(path), **({"clock": clock} if clock else {}))

        async def cleanup():
            while True:
                await asyncio.sleep(3600)
                app.state.auth.cleanup()

        task = asyncio.create_task(cleanup())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            app.state.auth.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    verification_slots = threading.BoundedSemaphore(4)
    skins = SkinCache(**({"loader": skin_loader} if skin_loader else {}))

    @app.middleware("http")
    async def limits(request, call_next):
        if request.url.path.startswith("/api/v1/auth/"):
            # Nginx also bounds streaming requests; do not accept chunked auth bodies.
            length = request.headers.get("content-length", "0")
            if (
                len(length) > 6
                or not length.isdigit()
                or int(length) > 4096
                or "transfer-encoding" in request.headers
            ):
                return Response(status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def browser(request):
        if request.headers.get("origin") != "https://mithril.foo":
            raise HTTPException(403, "Open this page on mithril.foo")

    def mod(request):
        if "origin" in request.headers:
            raise HTTPException(403, "Use the Minecraft mod")

    def require_link(request, token, consume=False):
        row = request.app.state.auth.get(token, "link", consume)
        if not row:
            raise HTTPException(410, "Link expired or already used. Create another in Minecraft.")
        return row

    def set_cookie(response, token, remembered):
        response.set_cookie(
            COOKIE,
            token,
            max_age=30 * DAY if remembered else None,
            secure=True,
            httponly=True,
            samesite="strict",
            path="/",
        )

    @app.post("/api/v1/auth/challenge")
    def challenge(body: Challenge, request: Request):
        mod(request)
        server_id = secrets.token_hex(20)[1:]
        token = request.app.state.auth.issue("challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "expires_in_seconds": 60,
        }

    @app.post("/api/v1/auth/verify")
    def verify(body: Proof, request: Request):
        mod(request)
        store = request.app.state.auth
        row = store.get(body.challenge_id, "challenge", consume=True)
        if not row:
            raise HTTPException(410, "Verification expired. Try again.")
        if not verification_slots.acquire(blocking=False):
            raise HTTPException(503, "Please try again later")
        try:
            profile = profile_lookup(row["name"], row["server_id"])
            valid = (
                isinstance(profile, dict)
                and UUID(profile.get("id", "")).hex == row["uuid"]
                and isinstance(profile.get("name"), str)
                and profile["name"].lower() == row["name"].lower()
                and row["expires"] > store.clock()
            )
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
            valid = False
        finally:
            verification_slots.release()
        if not valid:
            raise HTTPException(401, "Minecraft ownership could not be verified. Try again.")
        token = store.issue("link", row["uuid"], profile["name"], 300)
        receipt = store.issue("receipt", row["uuid"], profile["name"], 300, server_id=digest(token))
        return {
            "version": 1,
            "link_token": token,
            "receipt_token": receipt,
            "expires_in_seconds": 300,
        }

    @app.post("/api/v1/auth/link-status")
    def link_status(body: Link, request: Request):
        mod(request)
        return request.app.state.auth.receipt_status(body.token)

    @app.post("/api/v1/auth/preview")
    def preview(body: Link, request: Request):
        browser(request)
        return identity(require_link(request, body.token))

    @app.post("/api/v1/auth/complete")
    def complete(body: Complete, request: Request, response: Response):
        browser(request)
        row = require_link(request, body.token, consume=True)
        store = request.app.state.auth
        token = store.issue(
            "session",
            row["uuid"],
            row["name"],
            30 * DAY if body.remember else DAY,
            remembered=body.remember,
        )
        store.revoke(request.cookies.get(COOKIE, ""))
        store.confirm_receipts(body.token, token)
        set_cookie(response, token, body.remember)
        return {"authenticated": True, "user": identity(row)}

    @app.get("/api/v1/auth/session")
    def session(request: Request, response: Response):
        token = request.cookies.get(COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            return {"authenticated": False}
        store = request.app.state.auth
        row = store.get(token, "session")
        if not row:
            return {"authenticated": False}
        if row["remembered"] and row["expires"] - store.clock() < 29 * DAY:
            store.renew(token)
            set_cookie(response, token, True)
        return {"authenticated": True, "user": identity(row)}

    @app.get("/api/v1/auth/skin")
    def skin(request: Request):
        token = request.cookies.get(COOKIE, "")
        row = request.app.state.auth.get(token, "session")
        if not row:
            raise HTTPException(401, "Sign in first")
        result = skins.get(row["uuid"])
        if not result:
            raise HTTPException(503, "Skin unavailable. Try again later.")
        return result

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response):
        browser(request)
        request.app.state.auth.revoke(request.cookies.get(COOKIE, ""))
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
        return {"authenticated": False}

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["mithril.foo", "www.mithril.foo", "localhost", "127.0.0.1"],
    )

    @app.get("/api/v1/health", response_model=Health)
    def health(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return Health()

    return app


app = create_app()
