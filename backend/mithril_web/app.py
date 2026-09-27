"""Same-origin web API with separately scoped, ownership-proven mod submissions."""

import asyncio
import contextlib
import http.client
import os
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import COOKIE, DAY, AuthAttempts, AuthStore, CodeAttempts, digest, mojang_profile
from .parties import Finder
from .party_api import WAIT, StatsService, mojang_uuid, register
from .player_card import PlayerCardCache, fetch_card
from .records import RecordStore, Submission, with_mod_records
from .releases import ReleaseCache
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


class BrowserLink(StrictModel):
    token: str = Field(
        pattern=r"^(?:[A-Za-z0-9_-]{43}|[A-HJ-NP-Za-hj-np-z2-9]{4}-?[A-HJ-NP-Za-hj-np-z2-9]{4})$"
    )


class Complete(BrowserLink):
    remember: bool


class SyncChallenge(Challenge):
    receipt_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class SyncProof(Proof):
    receipt_token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


def identity(row):
    return {"uuid": row["uuid"], "name": row["name"]}


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["mithril-web"] = "mithril-web"
    api_version: Literal[1] = 1


def create_app(
    *,
    database=None,
    profile_lookup=mojang_profile,
    clock=None,
    skin_loader=None,
    card_loader=None,
    party_wait=WAIT,
    name_lookup=mojang_uuid,
    release_loader=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        path = database or Path(os.environ.get("MITHRIL_AUTH_DB", ".local/auth.sqlite3"))
        app.state.auth = AuthStore(Path(path), **({"clock": clock} if clock else {}))
        app.state.records = RecordStore(Path(path).with_name("records.sqlite3"))

        async def cleanup():
            while True:
                await asyncio.sleep(3600)
                app.state.auth.cleanup()

        tasks = [asyncio.create_task(cleanup()), asyncio.create_task(sweep_parties())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            app.state.auth.close()
            app.state.records.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # Anonymous links cannot occupy the capacity reserved for existing linked users.
    anonymous_slots = threading.BoundedSemaphore(2)
    linked_slots = threading.BoundedSemaphore(2)
    challenge_attempts = AuthAttempts(10, 300, clock=clock or time.monotonic)
    verification_attempts = AuthAttempts(20, 300, clock=clock or time.monotonic)
    code_attempts = CodeAttempts(clock=clock or time.monotonic)
    skins = SkinCache(**({"loader": skin_loader} if skin_loader else {}))
    cards = PlayerCardCache(**({"loader": card_loader} if card_loader else {}))
    releases = ReleaseCache(**({"loader": release_loader} if release_loader else {}))

    @app.middleware("http")
    async def limits(request, call_next):
        if request.url.path.startswith(("/api/v1/auth/", "/api/v1/party/")):
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
        if len(token) != 43:
            code_attempts.check(request.client.host if request.client else "unknown")
        row = request.app.state.auth.get_link(token, consume)
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
        challenge_attempts.check(request.client.host if request.client else "unknown")
        server_id = secrets.token_hex(20)[1:]
        token = request.app.state.auth.issue("challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "expires_in_seconds": 60,
        }

    def verify_ownership(request, challenge_id, kind):
        store = request.app.state.auth
        slots = anonymous_slots if kind == "challenge" else linked_slots
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "Please try again later", headers={"Retry-After": "1"})
        try:
            row = store.get(challenge_id, kind, consume=True)
            if not row:
                raise HTTPException(410, "Verification expired. Try again.")
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
            slots.release()
        if not valid:
            raise HTTPException(401, "Minecraft ownership could not be verified. Try again.")
        return {**row, "name": profile["name"]}

    @app.post("/api/v1/auth/verify")
    def verify(body: Proof, request: Request):
        mod(request)
        verification_attempts.check(request.client.host if request.client else "unknown")
        store = request.app.state.auth
        row = verify_ownership(request, body.challenge_id, "challenge")
        token = store.issue("link", row["uuid"], row["name"], 300)
        receipt = store.issue("receipt", row["uuid"], row["name"], 300, server_id=digest(token))
        code = store.issue_code(token)
        return {
            "version": 1,
            "link_token": token,
            "receipt_token": receipt,
            "user_code": code,
            "expires_in_seconds": 300,
        }

    @app.post("/api/v1/auth/sync-challenge")
    def sync_challenge(body: SyncChallenge, request: Request):
        return scoped_challenge(body, request, "sync")

    @app.post("/api/v1/auth/party-challenge")
    def party_challenge(body: SyncChallenge, request: Request):
        return scoped_challenge(body, request, "party")

    def scoped_challenge(body, request, scope):
        mod(request)
        store = request.app.state.auth
        session = store.linked_receipt(body.receipt_token)
        if not session or session["uuid"] != body.uuid:
            raise HTTPException(401, "Link your browser first")
        server_id = secrets.token_hex(20)[1:]
        token = store.issue(f"{scope}_challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "expires_in_seconds": 60,
        }

    @app.post("/api/v1/auth/sync-verify")
    def sync_verify(body: SyncProof, request: Request):
        return scoped_verify(body, request, "sync", 900)

    @app.post("/api/v1/auth/party-verify")
    def party_verify(body: SyncProof, request: Request):
        return scoped_verify(body, request, "party", 30 * DAY)

    def scoped_verify(body, request, scope, lifetime):
        mod(request)
        store = request.app.state.auth
        if not store.linked_receipt(body.receipt_token):
            raise HTTPException(401, "Link your browser first")
        row = verify_ownership(request, body.challenge_id, f"{scope}_challenge")
        session = store.linked_receipt(body.receipt_token)
        if not session or session["uuid"] != row["uuid"]:
            raise HTTPException(401, "Link your browser first")
        token = store.issue(scope, row["uuid"], row["name"], lifetime, server_id=session["token"])
        return {
            "version": 1,
            f"{scope}_token": token,
            "expires_in_seconds": lifetime,
            "user": identity(row),
        }

    @app.post("/api/v1/auth/sync-records")
    def sync_records(body: Submission, request: Request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
            raise HTTPException(401, "Mod authentication required")
        user = request.app.state.auth.sync_identity(authorization[7:])
        if not user:
            raise HTTPException(401, "Mod authentication expired")
        request.app.state.records.merge(user["uuid"], body.records)
        return {"version": 1, "user": user, "accepted": len(body.records)}

    @app.post("/api/v1/auth/link-status")
    def link_status(body: Link, request: Request):
        mod(request)
        return request.app.state.auth.receipt_status(body.token)

    @app.post("/api/v1/auth/preview")
    def preview(body: BrowserLink, request: Request):
        browser(request)
        row = require_link(request, body.token)
        session = request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        result = identity(row)
        if session and session["uuid"] == row["uuid"]:
            result["already_linked"] = True
        return result

    @app.post("/api/v1/auth/resume")
    def resume(body: BrowserLink, request: Request, response: Response):
        browser(request)
        store = request.app.state.auth
        token = request.cookies.get(COOKIE, "")
        session = store.get(token, "session")
        row = require_link(request, body.token)
        if not session or session["uuid"] != row["uuid"]:
            raise HTTPException(409, "Confirm this account before signing in")
        row = require_link(request, body.token, consume=True)
        store.renew(token)
        store.confirm_link_hash(row["token"], token)
        set_cookie(response, token, bool(session["remembered"]))
        return {"authenticated": True, "user": identity(row)}

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
        store.confirm_link_hash(row["token"], token)
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

    @app.get("/api/v1/party/skin/{uuid}")
    async def party_skin(uuid: str, request: Request):
        row = request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in first")
        if not re.fullmatch(r"[0-9a-f]{32}", uuid):
            raise HTTPException(404, "Skin unavailable")
        finder = request.app.state.finder
        viewer = finder.players.get(row["uuid"])
        party = finder.parties.get(viewer.party) if viewer else None
        # Retained chat can still contain messages from a member who has left.
        if uuid != row["uuid"] and (
            not party
            or row["uuid"] not in party.members()
            or (
                uuid not in party.members()
                and not any(m["sender"]["uuid"] == uuid for m in party.chat.messages)
            )
        ):
            raise HTTPException(404, "Player not in your party")
        result = await run_in_threadpool(skins.get, uuid)
        if not result:
            raise HTTPException(503, "Skin unavailable. Try again later.")
        return result

    @app.get("/api/v1/auth/player-card")
    def player_card(request: Request):
        row = request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in first")
        summary = cards.get(row["uuid"])
        if summary is None:
            raise HTTPException(503, "Player stats unavailable. Try again shortly.")
        summary = with_mod_records(summary, request.app.state.records.read(row["uuid"]))
        return {"version": 1, "user": identity(row), **summary}

    @app.get("/api/v1/party/player-card/{uuid}")
    async def party_player_card(uuid: str, request: Request):
        row = request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in first")
        finder = request.app.state.finder
        player = finder.players.get(uuid)
        party = finder.parties.get(player.party) if player else None
        if not party or (
            row["uuid"] not in party.members()
            and (party.paused or party.full_since is not None or row["uuid"] in party.blocked)
        ):
            raise HTTPException(404, "Player not in a visible party")
        user = {"uuid": player.uuid, "name": player.name}
        summary = await run_in_threadpool(cards.get, uuid)
        if summary is None:
            raise HTTPException(503, "Player stats unavailable. Try again shortly.")
        records = await run_in_threadpool(request.app.state.records.read, uuid)
        return {"version": 1, "user": user, **with_mod_records(summary, records)}

    sweep_parties = register(
        app,
        Finder(clock or time.time),
        StatsService(card_loader or fetch_card, lambda uuid: app.state.records.read(uuid)),
        browser,
        mod,
        wait=party_wait,
        name_lookup=name_lookup,
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["mithril.foo", "www.mithril.foo", "localhost", "127.0.0.1"],
    )

    @app.get("/api/v1/mod-release")
    def mod_release():
        return releases.get()

    @app.get("/api/v1/health", response_model=Health)
    def health(response: Response) -> Health:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return Health()

    return app


app = create_app()
