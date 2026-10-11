"""Capture routes: the mod's uploads, capturers' upload codes, roles and the review queue."""

import re
from typing import Annotated, Literal

from fastapi import HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .auth import COOKIE, DAY
from .capture import CaptureError, CaptureStore

# The oldest capture mod build allowed to upload; raise it to retire a broken build.
MINIMUM_VERSION = "0.1.0"
CODE_LIFETIME = 365 * DAY
MAX_IMAGE = 8 * 1024 * 1024
CODE_PATTERN = r"[A-Za-z0-9_-]{43}"
SubmissionId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{22}$")]
Island = Annotated[str, Field(pattern=r"^[a-z0-9_]{1,32}$")]
IslandName = Annotated[str, Field(min_length=1, max_length=48)]
ClientId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Coordinate = Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
Block = Annotated[int, Field(ge=-1_000_000, le=1_000_000)]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]


class NewLocation(Body):
    client_id: ClientId
    island: Island
    island_name: IslandName
    x: Coordinate
    y: Annotated[float, Field(ge=-2048, le=2048)]
    z: Coordinate
    captured_at: Annotated[int, Field(ge=0, le=10**14)]
    note: Annotated[str, Field(max_length=200)]
    face_size: Literal[1024, 2048]


class NewMap(Body):
    client_id: ClientId
    island: Island
    island_name: IslandName
    min_x: Block
    min_z: Block
    max_x: Block
    max_z: Block


class RevokeCode(Body):
    id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RoleChange(Body):
    uuid: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    role: Literal["capturer", "reviewer"]
    enabled: bool
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class Decision(Body):
    kind: Literal["locations", "maps"]
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{22}$")]
    decision: Literal["approve", "changes", "reject"]
    note: Annotated[str, Field(max_length=500)] = ""


def version_tuple(text):
    match = re.fullmatch(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:[-+].*)?", text or "")
    return tuple(int(part) for part in match.groups()) if match else (0, 0, 0)


def register_capture(app, browser, mod):
    def store() -> CaptureStore:
        return app.state.captures

    def handle(action):
        try:
            return action()
        except CaptureError as error:
            raise HTTPException(error.status, error.detail) from None

    def capturer(request, write=True):
        mod(request)
        authorization = request.headers.get("authorization", "")
        token = authorization[7:] if authorization.startswith("Bearer ") else ""
        row = app.state.auth.get(token, "capture") if re.fullmatch(CODE_PATTERN, token) else None
        if not row:
            raise HTTPException(401, "This upload code isn't valid any more. Create a new one.")
        if request.headers.get("x-capture-player") != row["uuid"]:
            raise HTTPException(403, "This upload code belongs to another Minecraft account")
        app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
        if "capturer" not in app.state.moderation.capture_roles(row["uuid"]):
            raise HTTPException(403, "You don't have the Capturer role")
        if write and version_tuple(request.headers.get("x-capture-version")) < version_tuple(
            MINIMUM_VERSION
        ):
            raise HTTPException(426, "Update the capture mod to upload")
        store().used(row["token"])
        return row

    def session(request):
        row = app.state.auth.get(request.cookies.get(COOKIE, ""), "session")
        if not row:
            raise HTTPException(401, "Sign in with your linked Minecraft account")
        app.state.moderation.check(row["uuid"], request.client.host if request.client else None)
        return row

    def reviewer(request):
        row = session(request)
        if "reviewer" not in app.state.moderation.capture_roles(row["uuid"]):
            raise HTTPException(403, "Reviewer access required")
        return row

    async def image_body(request):
        data = await request.body()
        if len(data) > MAX_IMAGE:
            raise HTTPException(413, "Images can be at most 8 MiB")
        if request.headers.get("content-type", "").split(";")[0].strip() != "image/png":
            raise HTTPException(422, "Images must be sent as image/png")
        return data

    # The capture mod

    @app.get("/api/v1/capture/me")
    def me(request: Request):
        row = capturer(request, write=False)
        return {
            "version": 1,
            "user": {"uuid": row["uuid"], "name": row["name"]},
            "minimum_version": MINIMUM_VERSION,
        }

    @app.get("/api/v1/capture/nearby")
    def nearby(
        request: Request,
        island: Annotated[str, Query(pattern=r"^[a-z0-9_]{1,32}$")],
        x: Annotated[float, Query(ge=-1_000_000, le=1_000_000)],
        z: Annotated[float, Query(ge=-1_000_000, le=1_000_000)],
    ):
        capturer(request, write=False)
        return {"version": 1, "locations": store().nearby(island, x, z)}

    @app.post("/api/v1/capture/locations")
    def create_location(body: NewLocation, request: Request):
        row = capturer(request)
        return handle(lambda: store().create_location(row, body))

    @app.put("/api/v1/capture/locations/{location_id}/faces/{face}")
    async def upload_face(
        location_id: SubmissionId, face: Annotated[int, Path(ge=0, le=5)], request: Request
    ):
        row = await run_in_threadpool(capturer, request)
        data = await image_body(request)
        return await run_in_threadpool(
            handle, lambda: store().upload_face(row["uuid"], location_id, face, data)
        )

    @app.post("/api/v1/capture/locations/{location_id}/finish")
    def finish_location(location_id: SubmissionId, body: Body, request: Request):
        row = capturer(request)
        return handle(lambda: store().finish_location(row["uuid"], location_id))

    @app.post("/api/v1/capture/maps")
    def create_map(body: NewMap, request: Request):
        row = capturer(request)
        return handle(lambda: store().create_map(row, body))

    @app.put("/api/v1/capture/maps/{map_id}/image")
    async def upload_map(map_id: SubmissionId, request: Request):
        row = await run_in_threadpool(capturer, request)
        data = await image_body(request)
        return await run_in_threadpool(
            handle, lambda: store().upload_map(row["uuid"], map_id, data)
        )

    @app.get("/api/v1/capture/submissions")
    def submissions(request: Request):
        return store().submissions(capturer(request, write=False)["uuid"])

    # Capturers in the browser

    @app.get("/api/v1/capture/account")
    def account(request: Request):
        row = session(request)
        roles = app.state.moderation.capture_roles(row["uuid"])
        codes = app.state.auth.capture_codes(row["uuid"])
        used = store().last_used([code["id"] for code in codes])
        return {
            "version": 1,
            "roles": roles,
            "codes": [
                {
                    "id": code["id"],
                    "created": int(code["expires"] - CODE_LIFETIME),
                    "last_used": int(used[code["id"]]) if code["id"] in used else None,
                }
                for code in codes
            ],
        }

    @app.post("/api/v1/capture/codes")
    def create_code(body: Body, request: Request):
        browser(request)
        row = session(request)
        if "capturer" not in app.state.moderation.capture_roles(row["uuid"]):
            raise HTTPException(403, "You don't have the Capturer role")
        return {
            "version": 1,
            "code": app.state.auth.issue_capture(row["uuid"], row["name"], CODE_LIFETIME),
        }

    @app.post("/api/v1/capture/codes/revoke")
    def revoke_code(body: RevokeCode, request: Request):
        browser(request)
        app.state.auth.revoke_capture(session(request)["uuid"], body.id)
        return {"version": 1}

    # The owner and reviewers

    @app.post("/api/v1/moderation/capture-role")
    def set_role(body: RoleChange, request: Request):
        browser(request)
        actor = session(request)["uuid"]
        app.state.moderation.set_capture_role(
            actor, body.uuid, body.role, body.enabled, body.reason.strip()
        )
        if body.role == "capturer" and not body.enabled:
            app.state.auth.revoke_capture(body.uuid)
        return {"version": 1}

    @app.get("/api/v1/moderation/captures")
    def review(
        request: Request,
        kind: Literal["locations", "maps"] = "locations",
        status: Literal[
            "submitted", "approved", "changes_requested", "rejected", "all"
        ] = "submitted",
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ):
        reviewer(request)
        return store().review(kind, status, offset)

    @app.post("/api/v1/moderation/captures/decide")
    def decide(body: Decision, request: Request):
        browser(request)
        actor = reviewer(request)["uuid"]
        handle(lambda: store().decide(actor, body.kind, body.id, body.decision, body.note))
        return {"version": 1}

    @app.get("/api/v1/moderation/captures/locations/{location_id}/faces/{face}.png")
    def face_image(
        location_id: SubmissionId, face: Annotated[int, Path(ge=0, le=5)], request: Request
    ):
        reviewer(request)
        data = handle(lambda: store().image("locations", location_id, face))
        return Response(data, media_type="image/png")

    @app.get("/api/v1/moderation/captures/maps/{map_id}.png")
    def map_image(map_id: SubmissionId, request: Request):
        reviewer(request)
        return Response(handle(lambda: store().image("maps", map_id)), media_type="image/png")
