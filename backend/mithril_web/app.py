"""Same-origin web API with separately scoped, ownership-proven mod submissions."""

import asyncio
import contextlib
import hashlib
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
from starlette.responses import JSONResponse

from .auth import COOKIE, DAY, AuthAttempts, AuthStore, CodeAttempts, mojang_profile
from .curator_api import register_curator
from .curator_data import CuratorData
from .link_previews import register_previews
from .moderation import Moderation
from .moderation_api import register_moderation
from .parties import Finder
from .party_api import WAIT, StatsService, mojang_uuid, register
from .player_card import PlayerCardCache, fetch_card
from .privacy import Privacy
from .privacy_api import register_privacy
from .records import RecordStore, Submission, with_mod_records
from .releases import ReleaseCache
from .run_maps import public_record
from .skins import SkinCache
from .slayer_market import SlayerMarket
from .solo_evidence import SoloProgress, SoloStart, TerminalReport

HEX_64_PATTERN = r"^[0-9a-f]{64}$"
BEARER_PATTERN = r"Bearer [A-Za-z0-9_-]{43}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Challenge(StrictModel):
    version: Literal[1]
    uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    client_nonce: str | None = Field(default=None, pattern=HEX_64_PATTERN)


class Proof(StrictModel):
    challenge_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class DeviceChallenge(Challenge):
    client_nonce: str = Field(pattern=HEX_64_PATTERN)


class RevokeDevice(StrictModel):
    id: str = Field(pattern=HEX_64_PATTERN)


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


def ownership_challenge(body: Challenge, scope: str) -> tuple[str, str | None]:
    # Compatibility for older clients; new clients never accept this legacy proof.
    if body.client_nonce is None:
        return secrets.token_hex(20)[1:], None
    nonce = secrets.token_hex(32)
    value = f"mithrilpf:ownership:v2:{scope}:{body.uuid}:{body.client_nonce}:{nonce}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:39], nonce


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
    slayer_loader=None,
    curator_loader=None,
    owner_uuid=None,
    network_key=None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        path = database or Path(os.environ.get("MITHRIL_AUTH_DB", ".local/auth.sqlite3"))
        app.state.auth = AuthStore(Path(path), **({"clock": clock} if clock else {}))
        app.state.records = RecordStore(
            Path(path).with_name("records.sqlite3"), clock=clock or time.time
        )
        key_path = os.environ.get("MITHRIL_NETWORK_KEY_FILE")
        app.state.moderation = Moderation(
            app.state.records,
            owner_uuid or os.environ.get("MITHRIL_OWNER_UUID"),
            network_key or (Path(key_path).read_bytes() if key_path else None),
        )
        app.state.privacy = Privacy(app.state.auth, app.state.moderation, Path(path).resolve())
        slayer_market.history_path = Path(path).with_name("pet-prices.sqlite3")
        app.state.curator = CuratorData(
            Path(path).with_name("curator.sqlite3"), loader=curator_loader, clock=clock or time.time
        )

        async def cleanup():
            while True:
                await asyncio.sleep(3600)
                await run_in_threadpool(app.state.auth.cleanup)
                await run_in_threadpool(app.state.records.cleanup)
                await run_in_threadpool(app.state.moderation.cleanup)
                await run_in_threadpool(app.state.privacy.cleanup)

        tasks = [
            asyncio.create_task(cleanup()),
            asyncio.create_task(sweep_parties()),
            asyncio.create_task(slayer_market.run()),
            asyncio.create_task(app.state.curator.run()),
        ]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            app.state.auth.close()
            app.state.records.close()
            app.state.curator.close()

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
    app.state.releases = releases
    slayer_market = SlayerMarket(**({"loader": slayer_loader} if slayer_loader else {}))

    @app.middleware("http")
    async def limits(request, call_next):
        if request.url.path.startswith(
            ("/api/v1/auth/", "/api/v1/party/", "/api/v1/records/", "/api/v1/moderation/")
        ):
            # Nginx also bounds streaming requests; do not accept chunked auth bodies.
            length = request.headers.get("content-length", "0")
            maximum = 640 * 1024 if request.url.path == "/api/v1/records/solo-progress" else 4096
            if (
                len(length) > 6
                or not length.isdigit()
                or int(length) > maximum
                or "transfer-encoding" in request.headers
            ):
                return Response(status_code=413)
        if request.url.path.startswith("/api/v1/party/"):
            try:
                await run_in_threadpool(party_access, request)
            except HTTPException as error:
                return JSONResponse(
                    {"detail": error.detail},
                    status_code=error.status_code,
                    headers={"Cache-Control": "no-store"},
                )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def party_access(request):
        authorization = request.headers.get("authorization", "")
        if request.url.path.startswith("/api/v1/party/client/"):
            row = device_user(request)
            app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
            return
        is_mod = request.url.path.startswith("/api/v1/party/mod/")
        row = (
            app.state.auth.party_identity(authorization[7:])
            if is_mod and re.fullmatch(BEARER_PATTERN, authorization)
            else app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        )
        if row:
            app.state.moderation.check(row["uuid"], request.client.host if request.client else None)

    def browser(request):
        if request.headers.get("origin") != "https://mithril.foo":
            raise HTTPException(403, "Open this page on mithril.foo")

    def mod(request):
        if "origin" in request.headers:
            raise HTTPException(403, "Use the Minecraft mod")

    def require_link(request, token):
        if len(token) != 43:
            code_attempts.check(request.client.host if request.client else "unknown")
        row = request.app.state.auth.get_link(token)
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
        server_id, nonce = ownership_challenge(body, "link")
        token = request.app.state.auth.issue("challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "server_nonce": nonce,
            "expires_in_seconds": 60,
        }

    def verify_ownership(request, challenge_id, kind):
        store = request.app.state.auth
        slots = anonymous_slots if kind in ("challenge", "device_challenge") else linked_slots
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
        token, receipt, code = store.issue_link(
            row["uuid"], row["name"], expected_epoch=row["_epoch"]
        )
        return {
            "version": 1,
            "link_token": token,
            "receipt_token": receipt,
            "user_code": code,
            "expires_in_seconds": 300,
        }

    @app.post("/api/v1/auth/device-challenge")
    def device_challenge(body: DeviceChallenge, request: Request):
        mod(request)
        challenge_attempts.check(request.client.host if request.client else "unknown")
        server_id, nonce = ownership_challenge(body, "device")
        token = app.state.auth.issue("device_challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "server_nonce": nonce,
            "expires_in_seconds": 60,
        }

    @app.post("/api/v1/auth/device-verify")
    def device_verify(body: Proof, request: Request):
        mod(request)
        verification_attempts.check(request.client.host if request.client else "unknown")
        row = verify_ownership(request, body.challenge_id, "device_challenge")
        token, receipt = app.state.auth.issue_device(row["uuid"], row["name"], row["_epoch"])
        return {
            "version": 1,
            "device_token": token,
            "receipt_token": receipt,
            "user": identity(row),
            "expires_in_seconds": 30 * DAY,
        }

    def device_user(request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        row = (
            app.state.auth.get(authorization[7:], "device")
            if re.fullmatch(BEARER_PATTERN, authorization)
            else None
        )
        if not row:
            raise HTTPException(401, "Minecraft session expired. Sign in again.")
        return row

    @app.get(
        "/api/v1/auth/device-session", responses={401: {"description": "Minecraft session expired"}}
    )
    def device_session(request: Request):
        row = device_user(request)
        return {"version": 1, "user": identity(row), "expires": row["expires"]}

    @app.post("/api/v1/auth/device-logout")
    def device_logout(request: Request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        if re.fullmatch(BEARER_PATTERN, authorization):
            app.state.auth.revoke_device(authorization[7:])
        return {"version": 1, "authenticated": False}

    @app.get("/api/v1/auth/devices")
    def devices(request: Request):
        return {"version": 1, "devices": app.state.auth.devices(request.cookies.get(COOKIE, ""))}

    @app.post("/api/v1/auth/devices/revoke")
    def revoke_device(body: RevokeDevice, request: Request):
        browser(request)
        app.state.auth.revoke_device(request.cookies.get(COOKIE, ""), body.id)
        return {"version": 1, "revoked": True}

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
        server_id, nonce = ownership_challenge(body, scope)
        token = store.issue(f"{scope}_challenge", body.uuid, body.name, 60, server_id)
        return {
            "version": 1,
            "challenge_id": token,
            "server_id": server_id,
            "server_nonce": nonce,
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
        token = store.issue(
            scope,
            row["uuid"],
            row["name"],
            lifetime,
            server_id=session["token"],
            expected_epoch=row["_epoch"],
        )
        return {
            "version": 1,
            f"{scope}_token": token,
            "expires_in_seconds": lifetime,
            "user": identity(row),
        }

    @app.post(
        "/api/v1/auth/sync-records", responses={410: {"description": "Use live record tracking"}}
    )
    def sync_records(body: Submission, request: Request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        if not re.fullmatch(BEARER_PATTERN, authorization):
            raise HTTPException(401, "Mod authentication required")
        user = request.app.state.auth.sync_identity(authorization[7:])
        if not user:
            raise HTTPException(401, "Mod authentication expired")
        raise HTTPException(
            410, "Update MithrilPF to submit new records. Existing synced PBs remain eligible."
        )

    def record_user(request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        if not re.fullmatch(BEARER_PATTERN, authorization):
            raise HTTPException(401, "Mod authentication required")
        user = request.app.state.auth.sync_identity(authorization[7:])
        if not user:
            raise HTTPException(401, "Mod authentication expired")
        request.app.state.moderation.check(
            user["uuid"], request.client.host if request.client else None, remember=True
        )
        return user

    def submit_record(request, method, body):
        # Authenticate again under the write lock: revocation/erasure cannot race a submission.
        with app.state.records.lock:
            user = record_user(request)
            uuid = user["uuid"]
            result = getattr(app.state.records, method)(uuid, body)
            if result.get("status") == "accepted":
                with app.state.records.db:
                    app.state.records.db.execute(
                        "INSERT OR REPLACE INTO record_names VALUES (?,?)", (uuid, user["name"])
                    )
            return uuid, result

    @app.get(
        "/api/v1/records/solo/{record_id}",
        responses={
            404: {"description": "Record unavailable"},
            503: {"description": "Map unavailable"},
        },
    )
    def solo_record(record_id: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", record_id):
            raise HTTPException(404, "Record unavailable")
        return public_record(app.state.records, record_id)

    @app.post("/api/v1/records/solo-start")
    async def solo_start(body: SoloStart, request: Request):
        _, result = await run_in_threadpool(submit_record, request, "start", body)
        return result

    @app.post("/api/v1/records/solo-progress")
    async def solo_progress(body: SoloProgress, request: Request):
        uuid, result = await run_in_threadpool(submit_record, request, "progress", body)
        if result["status"] == "accepted":
            await app.state.records_changed(uuid)
        return result

    @app.post("/api/v1/records/terminal-report")
    async def terminal_report(body: TerminalReport, request: Request):
        uuid, result = await run_in_threadpool(submit_record, request, "terminal", body)
        await app.state.records_changed(uuid)
        return result

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
        require_link(request, body.token)
        row, token, remember = store.finish_link(body.token, token)
        set_cookie(response, token, remember)
        return {"authenticated": True, "user": identity(row)}

    @app.post("/api/v1/auth/complete")
    def complete(body: Complete, request: Request, response: Response):
        browser(request)
        require_link(request, body.token)
        store = request.app.state.auth
        row, token, _ = store.finish_link(
            body.token,
            request.cookies.get(COOKIE, ""),
            remember=body.remember,
        )
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
        return {
            "authenticated": True,
            "user": identity(row),
            "moderator": bool(app.state.moderation.role(row["uuid"])),
        }

    @app.get("/api/v1/auth/skin", responses={401: {"description": "Session revoked"}})
    def skin(request: Request):
        token = request.cookies.get(COOKIE, "")
        row = request.app.state.auth.get(token, "session")
        if not row:
            raise HTTPException(401, "Sign in first")
        result = skins.get(row["uuid"])
        if not request.app.state.auth.get(token, "session"):
            skins.erase(row["uuid"])
            raise HTTPException(401, "Sign in first")
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

    @app.get("/api/v1/auth/device-player-card")
    @app.get("/api/v1/auth/player-card", responses={401: {"description": "Session revoked"}})
    def player_card(request: Request):
        native = request.url.path.endswith("device-player-card")
        row = (
            device_user(request)
            if native
            else request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        )
        if not row:
            raise HTTPException(401, "Sign in first")
        summary = cards.get(row["uuid"])
        if not (
            device_user(request)
            if native
            else request.app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        ):
            cards.erase(row["uuid"])
            raise HTTPException(401, "Sign in first")
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

    register_previews(app)
    register_moderation(app, browser, name_lookup)
    register_curator(app, browser)
    register_privacy(app, browser, skins, cards, device_user)

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["mithril.foo", "www.mithril.foo", "localhost", "127.0.0.1"],
    )

    @app.get("/api/v1/slayer-prices")
    def slayer_prices():
        return slayer_market.get()

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
