"""Versioned party-finder routes (v1). Everything touching Finder runs on the event loop.

Budget for ~2000 players on a small server: one held state request per client (answered
early only when that player's own state changes, otherwise after WAIT seconds, and
doubling as the presence heartbeat), a shared compact listing built once per change,
member details only on demand, and Hypixel profiles fetched at most every few hours.
"""

import asyncio
import http.client
import json
import re
import time
import zlib
from collections import OrderedDict, deque
from typing import Annotated, Literal

from fastapi import HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE
from .moderation_api import Action
from .parties import PartyError, player_stats

WAIT = 25  # clients re-request immediately, well inside the 60 s presence grace
SWEEP = 5
TRACKED_INTERVAL = 25  # mod heartbeat while this account uses the finder
IDLE_INTERVAL = 120  # otherwise game presence is only checked occasionally

Role = Literal["archer", "berserk", "healer", "mage", "tank"]
Floor = Literal["F7", "M7"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StateRequest(Strict):
    version: Literal[1]
    known: int | None = Field(default=None, ge=0)
    state_id: str | None = Field(default=None, max_length=80)


class ChatSend(Strict):
    version: Literal[1]
    party_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    text: str = Field(min_length=1, max_length=256)


class ChatRead(Strict):
    version: Literal[1]
    party_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    after: int = Field(default=0, ge=0, le=2**53 - 1)


class LookRequest(Strict):
    version: Literal[1]
    floor: Floor
    classes: list[Role] = Field(min_length=1, max_length=5)
    max_team_s_plus_ms: int | None = Field(default=None, ge=1, le=7_200_000)


class ReserveRequest(Strict):
    party_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    role: Role


class Rules(Strict):
    shared: dict[str, int] = Field(default_factory=dict, max_length=7)
    per_class: dict[Role, dict[str, int]] = Field(default_factory=dict)
    exempt: list[Role] = Field(default_factory=list, max_length=5)


Names = list[Annotated[str, Field(pattern=r"^[A-Za-z0-9_]{1,16}$")]]


class EditRequest(Strict):
    rules: Rules
    # Already-blocked UUIDs to keep (renames never unblock) plus new names to resolve.
    blocked: list[Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]] = Field(
        default_factory=list, max_length=100
    )
    block_names: Names = Field(default_factory=list, max_length=100)


class PublishRequest(Strict):
    rules: Rules
    block_names: Names = Field(default_factory=list, max_length=100)
    version: Literal[1]
    floor: Floor
    leader_class: Role
    roles: list[Role] = Field(min_length=5, max_length=5)
    allow_duplicates: bool


class PauseRequest(Strict):
    paused: bool


class RemoveRequest(Strict):
    member: str = Field(pattern=r"^[0-9a-f]{32}$")
    block: bool


class Empty(Strict):
    pass


class ChatReport(Action):
    party_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    message_id: str = Field(pattern=r"^[0-9]{1,12}$")


class ModPresence(Strict):
    version: Literal[1]
    online: bool = True


class ModRoster(Strict):
    version: Literal[1]
    party_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    handoff_id: str = Field(pattern=r"^[A-Za-z0-9_-]{12}$")
    leader: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    members: Names = Field(min_length=1, max_length=5)


class ModInvite(ModRoster):
    retry: bool


def mojang_uuid(name):
    """Current UUID and name for a Minecraft username, or None if nobody has it."""
    connection = http.client.HTTPSConnection("api.mojang.com", timeout=4)
    try:
        connection.request(
            "GET",
            f"/users/profiles/minecraft/{name}",
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        if response.status in (204, 404):
            return None
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("Name lookup unavailable")
        body = response.read(4097)
        if len(body) > 4096:
            raise ValueError("Response too large")
        data = json.loads(body)
        uuid, current = data.get("id"), data.get("name")
        if not re.fullmatch(r"[0-9a-f]{32}", str(uuid)) or not re.fullmatch(
            r"[A-Za-z0-9_]{1,16}", str(current)
        ):
            raise ValueError("Invalid profile")
        return uuid, current
    finally:
        connection.close()


def status(code):
    if code == "chat_rate_limited":
        return 429
    if code.startswith("invalid"):
        return 422
    return {"not_found": 404, "capacity": 503, "stats_unavailable": 503}.get(code, 409)


class StatsService:
    """Hypixel summaries cached for hours; mod records re-read on every refresh.

    A profiles response can be megabytes, so fetches are rare: 6 h per player, two at a
    time, a per-minute budget, and a one-minute pause after a failure.
    """

    def __init__(self, loader, records, clock=time.monotonic, ttl=6 * 3600, budget=30):
        self.loader, self.records, self.clock = loader, records, clock
        self.ttl, self.budget = ttl, budget
        self.entries = OrderedDict()
        self.failed = {}
        self.pending = set()
        self.erased_pending = set()
        self.attempts = deque()

    async def get(self, uuid):
        now = self.clock()
        entry = self.entries.get(uuid)
        if entry is None or entry[0] <= now - self.ttl:
            if summary := await self._fetch(uuid, now):
                entry = self.entries[uuid] = (now, summary)
                self.entries.move_to_end(uuid)
                while len(self.entries) > 4000:
                    self.entries.popitem(last=False)
        if entry is None:
            return None
        return player_stats(entry[1], await run_in_threadpool(self.records, uuid))

    async def _fetch(self, uuid, now):
        while self.attempts and self.attempts[0] <= now - 60:
            self.attempts.popleft()
        if (
            uuid in self.pending
            or len(self.pending) >= 2
            or len(self.attempts) >= self.budget
            or self.failed.get(uuid, float("-inf")) > now - 60
        ):
            return None
        self.pending.add(uuid)
        self.attempts.append(now)
        try:
            result = await run_in_threadpool(self.loader, uuid)
            if uuid in self.erased_pending:
                return None
            return result
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            self.failed[uuid] = now
            if len(self.failed) > 4000:
                self.failed = {k: v for k, v in self.failed.items() if v > now - 60}
            return None
        finally:
            self.pending.discard(uuid)
            self.erased_pending.discard(uuid)


class Waiters:
    """One event per waiting account; waking pops it so every waiting tab returns."""

    def __init__(self):
        self.events = {}

    def wake(self, uuids):
        for uuid in uuids:
            if event := self.events.pop(uuid, None):
                event.set()

    async def wait(self, uuid, timeout):
        event = self.events.setdefault(uuid, asyncio.Event())
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except TimeoutError:
            pass


def register(app, finder, stats, browser, mod, *, wait=WAIT, name_lookup=mojang_uuid):
    """Add the v1 party routes. Returns the sweep loop for the app lifespan to run."""
    waiters = Waiters()
    resolving = [0]
    fragments = {}  # party id -> (public_version, serialized listing)
    app.state.finder = finder

    def run(action):
        try:
            return action()
        except PartyError as error:
            raise HTTPException(status(error.code), error.code) from None
        finally:
            waiters.wake(finder.drain())

    async def records_changed(uuid):
        records = await run_in_threadpool(app.state.records.read, uuid)
        player = finder.players.get(uuid)
        if player and player.stats is not None:
            # Re-read PBs without fetching Hypixel; invalidations must clear cached minima.
            values = player_stats({}, records)
            fresh = {
                **player.stats,
                "solo_ms": values["solo_ms"],
                "terminals_ms": values["terminals_ms"],
            }
            run(lambda: finder.set_stats(uuid, fresh))

    def remove_players(uuids):
        for uuid in uuids:
            player = finder.players.get(uuid)
            if not player:
                continue
            run(lambda uuid=uuid: finder.stop_looking(uuid))
            if player.party:
                run(lambda uuid=uuid: finder.leave(uuid))
            finder.players.pop(uuid, None)
            waiters.wake([uuid])

    def hide_message(party_id, message_id):
        party = finder.parties.get(party_id)
        if not party:
            return
        party.chat.hide(message_id)
        for uuid in party.members():
            finder._touch(finder.players[uuid])
        waiters.wake(finder.drain())

    def erase_player(uuid):
        stats.entries.pop(uuid, None)
        stats.failed.pop(uuid, None)
        if uuid in stats.pending:
            stats.erased_pending.add(uuid)
        for party in list(finder.parties.values()):
            for message in list(party.chat.messages):
                if (message.get("sender") or {}).get("uuid") == uuid:
                    hide_message(party.id, message["id"])
            for key in [key for key in party.chat.receipts if key[0] == uuid]:
                del party.chat.receipts[key]
        remove_players([uuid])

    app.state.erase_player = erase_player

    app.state.hide_message = hide_message

    app.state.records_changed = records_changed
    app.state.remove_players = remove_players

    async def allowed(request, row, remember=False):
        await run_in_threadpool(
            app.state.moderation.check,
            row["uuid"],
            request.client.host if request.client else None,
            request.url.path in ("/api/v1/party/chat", "/api/v1/party/mod/chat/send"),
            remember,
        )
        return row

    async def session(request):
        row = await run_in_threadpool(
            request.app.state.auth.get, request.cookies.get(COOKIE, ""), "session"
        )
        if not row:
            raise HTTPException(401, "Sign in first")
        return await allowed(request, row)

    async def enter(request, refresh=False):
        browser(request)
        row = await session(request)
        player = run(lambda: finder.seen(row["uuid"], row["name"], "web"))
        if refresh or player.stats is None:
            fresh = await stats.get(row["uuid"])
            await session(request)
            if row["uuid"] in finder.players:
                run(lambda: finder.set_stats(row["uuid"], fresh))
        return row["uuid"]

    async def resolve(names):
        """Names to {uuid: name}: finder users first, then at most 10 Mojang lookups."""
        known = {player.name.lower(): player for player in finder.players.values()}
        found, missing = {}, []
        for name in dict.fromkeys(name.lower() for name in names):
            if player := known.get(name):
                found[player.uuid] = player.name
            else:
                missing.append(name)
        if len(missing) > 10:
            raise HTTPException(422, "too_many_names")
        if missing and resolving[0] >= 2:
            raise HTTPException(503, "capacity")
        unknown = []
        resolving[0] += 1
        try:
            for name in missing:
                try:
                    result = await run_in_threadpool(name_lookup, name)
                except (OSError, ValueError, TypeError, http.client.HTTPException):
                    raise HTTPException(503, "name_lookup_unavailable") from None
                if result:
                    found[result[0]] = result[1]
                else:
                    unknown.append(name)
        finally:
            resolving[0] -= 1
        if unknown:
            raise HTTPException(422, {"code": "unknown_names", "names": unknown})
        return found

    async def act(request, action, refresh=False):
        uuid = await enter(request, refresh)
        run(lambda: action(uuid))
        return finder.personal(uuid)

    @app.post("/api/v1/party/state")
    async def state(body: StateRequest, request: Request):
        uuid = await enter(request)
        same_state = body.state_id is None or body.state_id == finder.players[uuid].state_id
        if same_state and body.known is not None and body.known == finder.players[uuid].version:
            await waiters.wait(uuid, wait)
        await session(request)  # A logout/expiry during the held request must revoke chat too.
        player = finder.players.get(uuid)
        if player is None:
            raise HTTPException(409, "unknown_player")
        if same_state and body.known is not None and body.known == player.version:
            return {"version": 1, "state_version": player.version, "unchanged": True}
        return finder.personal(uuid)

    @app.post("/api/v1/party/chat")
    async def chat(body: ChatSend, request: Request):
        browser(request)
        uuid = (await session(request))["uuid"]
        run(
            lambda: finder.send_chat(uuid, body.party_id, body.request_id, body.text, "web"),
        )
        return finder.personal(uuid)

    @app.post("/api/v1/party/chat/report")
    async def report_chat(body: ChatReport, request: Request):
        browser(request)
        uuid = (await session(request))["uuid"]
        view = run(lambda: finder.chat_view(uuid, body.party_id))
        message = next((m for m in view["messages"] if m["id"] == body.message_id), None)
        if not message or not message.get("sender"):
            raise HTTPException(404, "Message unavailable")
        snapshot = dict(message)

        def save_report():
            with app.state.records.lock:
                current = app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
                if not current or current["uuid"] != uuid:
                    raise HTTPException(401, "Sign in first")
                return app.state.moderation.chat.submit(uuid, body.party_id, snapshot, body.reason)

        report_id = await run_in_threadpool(save_report)
        return {"version": 1, "report_id": report_id}

    @app.post("/api/v1/party/look")
    async def look(body: LookRequest, request: Request):
        return await act(
            request,
            lambda uuid: finder.look(uuid, body.floor, body.classes, body.max_team_s_plus_ms),
            refresh=True,
        )

    @app.post("/api/v1/party/stop-looking")
    async def stop_looking(body: Empty, request: Request):
        return await act(request, finder.stop_looking)

    @app.post("/api/v1/party/reserve")
    async def reserve(body: ReserveRequest, request: Request):
        return await act(
            request, lambda uuid: finder.reserve(uuid, body.party_id, body.role), refresh=True
        )

    @app.post("/api/v1/party/leave")
    async def leave(body: Empty, request: Request):
        return await act(request, finder.leave)

    @app.post("/api/v1/party/publish")
    async def publish(body: PublishRequest, request: Request):
        uuid = await enter(request, refresh=True)
        if finder.players[uuid].party:
            raise HTTPException(409, "in_party")
        blocked = await resolve(body.block_names)
        await session(request)
        run(
            lambda: finder.publish(
                uuid,
                body.floor,
                body.leader_class,
                body.roles,
                body.allow_duplicates,
                body.rules.model_dump(),
                blocked,
            ),
        )
        return finder.personal(uuid)

    @app.post("/api/v1/party/edit")
    async def edit(body: EditRequest, request: Request):
        uuid = await enter(request)
        run(lambda: finder._led(uuid))
        added = await resolve(body.block_names)
        await session(request)
        run(lambda: finder.edit(uuid, body.rules.model_dump(), body.blocked, added))
        return finder.personal(uuid)

    @app.post("/api/v1/party/pause")
    async def pause(body: PauseRequest, request: Request):
        return await act(request, lambda uuid: finder.pause(uuid, body.paused))

    @app.post("/api/v1/party/unlist")
    async def unlist(body: Empty, request: Request):
        return await act(request, finder.unlist)

    @app.post("/api/v1/party/remove")
    async def remove(body: RemoveRequest, request: Request):
        return await act(request, lambda uuid: finder.remove(uuid, body.member, body.block))

    @app.get("/api/v1/party/listings")
    async def listings(floor: Floor, request: Request):
        """Shared compact rows; send the ETag back as If-None-Match to get a 304."""
        viewer = (await session(request))["uuid"]
        viewer_tag = zlib.crc32(viewer.encode())
        tag = f'"{finder.epoch}-{floor}-{finder.floor_version[floor]}-{viewer_tag:x}"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag})
        for stale in [key for key in fragments if key not in finder.parties]:
            del fragments[stale]
        rows = []
        for party in finder.parties.values():
            if party.completed or party.floor != floor or party.full_since is not None:
                continue
            if party.paused or viewer in party.blocked:
                continue
            cached = fragments.get(party.id)
            if cached is None or cached[0] != party.public_version:
                cached = fragments[party.id] = (
                    party.public_version,
                    json.dumps(finder.listing(party), separators=(",", ":")).encode(),
                )
            rows.append(cached[1])
        body = b'{"version":1,"floor":"%s","parties":[%s]}' % (floor.encode(), b",".join(rows))
        return Response(body, media_type="application/json", headers={"ETag": tag})

    @app.get("/api/v1/party/listings/{party_id}")
    async def detail(party_id: str, request: Request):
        viewer = (await session(request))["uuid"]
        party = finder.parties.get(party_id)
        if (
            not party
            or party.paused
            or viewer in party.blocked
            or (party.completed and viewer not in party.members())
        ):
            raise HTTPException(404, "not_found")
        return {"version": 1, **finder.detail(party)}

    async def mod_user(request):
        mod(request)
        authorization = request.headers.get("authorization", "")
        if not re.fullmatch(r"Bearer [A-Za-z0-9_-]{43}", authorization):
            raise HTTPException(401, "Mod authentication required")
        user = await run_in_threadpool(request.app.state.auth.party_identity, authorization[7:])
        if not user:
            raise HTTPException(401, "Mod authentication expired")
        return await allowed(request, user, remember=True)

    @app.post("/api/v1/party/mod/chat/send")
    async def mod_chat_send(body: ChatSend, request: Request):
        user = await mod_user(request)
        message = run(
            lambda: finder.send_chat(
                user["uuid"], body.party_id, body.request_id, body.text, "game"
            )
        )
        return {"version": 1, "message": message}

    @app.post("/api/v1/party/mod/chat/state")
    async def mod_chat_state(body: ChatRead, request: Request):
        user = await mod_user(request)
        view = run(lambda: finder.chat_view(user["uuid"], body.party_id, body.after))
        if view["latest"] == body.after:
            await waiters.wait(user["uuid"], wait)
        await mod_user(request)
        return run(lambda: finder.chat_view(user["uuid"], body.party_id, body.after))

    @app.post("/api/v1/party/mod/presence")
    async def presence(body: ModPresence, request: Request):
        """Online means connected to Hypixel, not simply that Minecraft is running."""
        user = await mod_user(request)
        run(lambda: finder.seen(user["uuid"], user["name"], "mod", body.online))
        tracked = user["uuid"] in finder.players
        return {
            "version": 1,
            "interval_seconds": TRACKED_INTERVAL if tracked else IDLE_INTERVAL,
            "party": finder.handoff(user["uuid"]),
            "chat_party_id": finder.players[user["uuid"]].party if tracked else None,
            "activity": finder.activity(user["uuid"]),
        }

    @app.post("/api/v1/party/mod/roster")
    async def roster(body: ModRoster, request: Request):
        user = await mod_user(request)
        run(
            lambda: finder.report_roster(
                user["uuid"], body.party_id, body.handoff_id, body.leader, body.members
            )
        )
        return {
            "version": 1,
            "party": finder.handoff(user["uuid"]),
            "activity": finder.activity(user["uuid"]),
        }

    @app.post("/api/v1/party/mod/invite")
    async def invite(body: ModInvite, request: Request):
        user = await mod_user(request)
        names = run(
            lambda: finder.invite(
                user["uuid"], body.party_id, body.handoff_id, body.leader, body.members, body.retry
            )
        )
        return {
            "version": 1,
            "invite": names,
            "party": finder.handoff(user["uuid"]),
            "activity": finder.activity(user["uuid"]),
        }

    async def sweep_loop():
        while True:
            await asyncio.sleep(SWEEP)
            run(finder.sweep)
            for uuid in [key for key in waiters.events if key not in finder.players]:
                waiters.events.pop(uuid).set()

    return sweep_loop
