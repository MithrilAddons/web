import io
import uuid as uuids

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.auth import COOKIE, DAY
from mithril_web.capture import DAILY_LIMIT, reencode
from mithril_web.capture_api import version_tuple
from PIL import Image

NOW = 1_800_000_000.0
OWNER, ALICE, BOB = (char * 32 for char in "abc")
ORIGIN = "https://mithril.foo"


def png(width, height=None, fmt="PNG"):
    output = io.BytesIO()
    image = Image.new("RGB", (width, height or width), (90, 120, 200))
    image.info["comment"] = "private metadata"
    image.save(output, fmt)
    return output.getvalue()


FACE = png(1024)


@pytest.fixture
def capture(tmp_path):
    now = [NOW]
    app = create_app(database=tmp_path / "auth.db", clock=lambda: now[0], owner_uuid=OWNER)
    with TestClient(app, base_url="https://mithril.foo") as client:
        auth = app.state.auth
        sessions = {
            who: {"Cookie": f"{COOKIE}={auth.issue('session', who, name, DAY)}", "Origin": ORIGIN}
            for who, name in ((OWNER, "Owner"), (ALICE, "Alice"), (BOB, "Bob"))
        }

        def grant(who, role="capturer", enabled=True):
            return client.post(
                "/api/v1/moderation/capture-role",
                headers=sessions[OWNER],
                json={
                    "version": 1,
                    "uuid": who,
                    "role": role,
                    "enabled": enabled,
                    "reason": "Synthetic",
                },
            )

        def code(who):
            response = client.post(
                "/api/v1/capture/codes", headers=sessions[who], json={"version": 1}
            )
            assert response.status_code == 200, response.text
            token = response.json()["code"]
            return {
                "Authorization": f"Bearer {token}",
                "X-Capture-Player": who,
                "X-Capture-Version": "0.1.0",
            }

        yield client, app, now, sessions, grant, code


def location(client, mod, client_id=None, island="hub", x=10.0, z=20.0, size=1024):
    return client.post(
        "/api/v1/capture/locations",
        headers=mod,
        json={
            "version": 1,
            "client_id": client_id or str(uuids.uuid4()),
            "island": island,
            "island_name": "Hub",
            "x": x,
            "y": 72.0,
            "z": z,
            "captured_at": 1,
            "note": "top of the bank",
            "face_size": size,
        },
    )


def upload(client, mod, location_id, face, data=FACE, kind="image/png"):
    return client.put(
        f"/api/v1/capture/locations/{location_id}/faces/{face}",
        headers={**mod, "Content-Type": kind},
        content=data,
    )


def finish(client, mod, location_id):
    return client.post(
        f"/api/v1/capture/locations/{location_id}/finish", headers=mod, json={"version": 1}
    )


def submitted(client, mod, **kwargs):
    location_id = location(client, mod, **kwargs).json()["id"]
    for face in range(6):
        assert upload(client, mod, location_id, face).status_code == 200
    assert finish(client, mod, location_id).json()["status"] == "submitted"
    return location_id


def test_capturers_need_the_role_and_their_own_code(capture):
    client, app, _, sessions, grant, code = capture
    assert (
        client.post(
            "/api/v1/capture/codes", headers=sessions[ALICE], json={"version": 1}
        ).status_code
        == 403
    )
    assert grant(ALICE).status_code == 200
    # Only the owner can grant roles.
    denied = client.post(
        "/api/v1/moderation/capture-role",
        headers=sessions[ALICE],
        json={"version": 1, "uuid": BOB, "role": "capturer", "enabled": True, "reason": "x"},
    )
    assert denied.status_code == 403
    mod = code(ALICE)
    me = client.get("/api/v1/capture/me", headers=mod).json()
    assert me == {
        "version": 1,
        "user": {"uuid": ALICE, "name": "Alice"},
        "minimum_version": "0.1.0",
    }
    account = client.get("/api/v1/capture/account", headers=sessions[ALICE]).json()
    assert account["roles"] == ["capturer"]
    assert account["codes"][0]["last_used"] == int(NOW)
    assert account["codes"][0]["created"] == int(NOW)
    assert (
        client.get("/api/v1/capture/me", headers={**mod, "X-Capture-Player": BOB}).status_code
        == 403
    )
    assert client.get("/api/v1/capture/me", headers={**mod, "Origin": ORIGIN}).status_code == 403
    assert client.get("/api/v1/capture/me").status_code == 401
    assert (
        client.get("/api/v1/capture/me", headers={**mod, "Authorization": "Bearer x"}).status_code
        == 401
    )
    # Removing the role revokes every code.
    grant(ALICE, enabled=False)
    assert client.get("/api/v1/capture/me", headers=mod).status_code == 401
    owner = client.get("/api/v1/capture/account", headers=sessions[OWNER]).json()
    assert owner["roles"] == ["capturer", "reviewer"]


def test_codes_can_be_listed_and_revoked(capture):
    client, app, _, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    codes = client.get("/api/v1/capture/account", headers=sessions[ALICE]).json()["codes"]
    assert len(codes) == 1 and codes[0]["last_used"] is None
    revoke = client.post(
        "/api/v1/capture/codes/revoke",
        headers=sessions[ALICE],
        json={"version": 1, "id": codes[0]["id"]},
    )
    assert revoke.status_code == 200
    assert client.get("/api/v1/capture/me", headers=mod).status_code == 401
    assert (
        client.post(
            "/api/v1/capture/codes/revoke",
            headers=sessions[ALICE],
            json={"version": 1, "id": codes[0]["id"]},
        ).status_code
        == 404
    )
    for _ in range(10):
        code(ALICE)
    assert (
        client.post(
            "/api/v1/capture/codes", headers=sessions[ALICE], json={"version": 1}
        ).status_code
        == 409
    )


def test_a_location_uploads_resumes_and_submits(capture):
    client, app, _, _, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    client_id = str(uuids.uuid4())
    created = location(client, mod, client_id).json()
    assert created["status"] == "uploading" and created["faces"] == []
    assert upload(client, mod, created["id"], 0).json()["faces"] == [0]
    assert upload(client, mod, created["id"], 3).json()["faces"] == [0, 3]
    # The same client_id resumes the same location.
    again = location(client, mod, client_id).json()
    assert (again["id"], again["faces"]) == (created["id"], [0, 3])
    assert finish(client, mod, created["id"]).status_code == 409
    for face in (1, 2, 4, 5):
        upload(client, mod, created["id"], face)
    assert finish(client, mod, created["id"]).json() == {"version": 1, "status": "submitted"}
    assert finish(client, mod, created["id"]).json()["status"] == "submitted"
    assert upload(client, mod, created["id"], 0).status_code == 409
    stored = app.state.captures.face_path(created["id"], 0).read_bytes()
    with Image.open(io.BytesIO(stored)) as image:
        assert "comment" not in image.info and image.size == (1024, 1024)
    listed = client.get("/api/v1/capture/submissions", headers=mod).json()
    assert listed["locations"][0]["status"] == "submitted"
    assert listed["locations"][0]["client_id"] == client_id


def test_bad_uploads_are_refused(capture):
    client, app, _, _, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    location_id = location(client, mod).json()["id"]
    assert upload(client, mod, location_id, 0, png(512)).status_code == 422
    assert upload(client, mod, location_id, 0, png(1024, fmt="JPEG")).status_code == 422
    assert upload(client, mod, location_id, 0, b"not an image").status_code == 422
    assert upload(client, mod, location_id, 0, kind="image/jpeg").status_code == 422
    assert upload(client, mod, location_id, 6).status_code == 422
    assert upload(client, mod, "x" * 22, 0).status_code == 404
    too_big = upload(client, mod, location_id, 0, b"\0" * (8 * 1024 * 1024 + 1))
    assert too_big.status_code == 413
    assert location(client, mod, island="dynamic").status_code == 422
    assert location(client, mod, size=512).status_code == 422
    old = {**mod, "X-Capture-Version": "0.0.9"}
    assert location(client, old).status_code == 426
    assert client.get("/api/v1/capture/me", headers=old).status_code == 200
    grant(BOB)
    bob = code(BOB)
    assert upload(client, bob, location_id, 0).status_code == 404


def test_nearby_finds_live_and_pending_locations(capture):
    client, app, _, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    first = submitted(client, mod, x=10.0, z=20.0)
    submitted(client, mod, x=40.0, z=20.0)
    location(client, mod, x=12.0, z=20.0)  # still uploading: not listed
    client.post(
        "/api/v1/moderation/captures/decide",
        headers=sessions[OWNER],
        json={"version": 1, "kind": "locations", "id": first, "decision": "approve"},
    )
    found = client.get("/api/v1/capture/nearby?island=hub&x=13&z=24", headers=mod).json()
    assert found["locations"] == [{"x": 10.0, "z": 20.0, "distance": 5.0, "status": "live"}]
    assert (
        client.get("/api/v1/capture/nearby?island=farming_1&x=13&z=24", headers=mod).json()[
            "locations"
        ]
        == []
    )


def test_maps_upload_and_replace_older_unreviewed_ones(capture):
    client, app, _, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)

    def new_map(width=64, height=32):
        return client.post(
            "/api/v1/capture/maps",
            headers=mod,
            json={
                "version": 1,
                "client_id": str(uuids.uuid4()),
                "island": "hub",
                "island_name": "Hub",
                "min_x": -10,
                "min_z": -5,
                "max_x": -10 + width - 1,
                "max_z": -5 + height - 1,
            },
        )

    first = new_map().json()["id"]
    put = client.put(
        f"/api/v1/capture/maps/{first}/image",
        headers={**mod, "Content-Type": "image/png"},
        content=png(64, 32),
    )
    assert put.json() == {"version": 1, "status": "submitted"}
    assert (
        client.put(
            f"/api/v1/capture/maps/{first}/image",
            headers={**mod, "Content-Type": "image/png"},
            content=png(64, 32),
        ).status_code
        == 409
    )
    second = new_map().json()["id"]
    assert (
        client.put(
            f"/api/v1/capture/maps/{second}/image",
            headers={**mod, "Content-Type": "image/png"},
            content=png(32, 32),
        ).status_code
        == 422
    )
    client.put(
        f"/api/v1/capture/maps/{second}/image",
        headers={**mod, "Content-Type": "image/png"},
        content=png(64, 32),
    )
    maps = {
        m["id"]: m for m in client.get("/api/v1/capture/submissions", headers=mod).json()["maps"]
    }
    assert maps[first]["status"] == "rejected"
    assert maps[first]["reviewer_note"] == "Replaced by a newer map"
    assert maps[second]["status"] == "submitted"
    assert new_map(width=5000).status_code == 422
    assert (
        client.put(
            "/api/v1/capture/maps/" + "y" * 22 + "/image",
            headers={**mod, "Content-Type": "image/png"},
            content=png(8),
        ).status_code
        == 404
    )
    # Approving makes it the island's current map in the review queue.
    client.post(
        "/api/v1/moderation/captures/decide",
        headers=sessions[OWNER],
        json={"version": 1, "kind": "maps", "id": second, "decision": "approve"},
    )
    queue = client.get(
        "/api/v1/moderation/captures?kind=maps&status=all", headers=sessions[OWNER]
    ).json()
    assert queue["current_maps"]["hub"] == {
        "id": second,
        "min_x": -10,
        "min_z": -5,
        "max_x": 53,
        "max_z": 26,
    }
    image = client.get(f"/api/v1/moderation/captures/maps/{second}.png", headers=sessions[OWNER])
    assert image.headers["content-type"] == "image/png"


def test_reviewers_decide_with_a_note(capture):
    client, app, _, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    location_id = submitted(client, mod)
    uploading = location(client, mod).json()["id"]
    queue = client.get("/api/v1/moderation/captures", headers=sessions[OWNER]).json()
    assert queue["total"] == 1 and queue["items"][0]["name"] == "Alice"
    assert "uuid" not in queue["items"][0]
    assert client.get("/api/v1/moderation/captures", headers=sessions[BOB]).status_code == 403

    def decide(who, decision, note="", item=location_id):
        return client.post(
            "/api/v1/moderation/captures/decide",
            headers=sessions[who],
            json={
                "version": 1,
                "kind": "locations",
                "id": item,
                "decision": decision,
                "note": note,
            },
        )

    assert decide(OWNER, "changes").status_code == 422
    assert decide(OWNER, "approve", item=uploading).status_code == 409
    assert decide(OWNER, "approve", item="z" * 22).status_code == 404
    grant(BOB, "reviewer")
    assert decide(BOB, "changes", "a player is visible").status_code == 200
    status = client.get("/api/v1/capture/submissions", headers=mod).json()["locations"]
    current = next(row for row in status if row["id"] == location_id)
    assert current["status"] == "changes_requested"
    assert current["reviewer_note"] == "a player is visible"
    face = client.get(
        f"/api/v1/moderation/captures/locations/{location_id}/faces/2.png", headers=sessions[BOB]
    )
    assert face.status_code == 200
    assert (
        client.get(
            f"/api/v1/moderation/captures/locations/{uploading}/faces/2.png", headers=sessions[BOB]
        ).status_code
        == 404
    )
    home = client.get("/api/v1/moderation/access", headers=sessions[BOB]).json()
    assert home["role"] == "reviewer" and home["capture_roles"] == ["reviewer"]
    assert (
        client.get(f"/api/v1/moderation/player/{ALICE}", headers=sessions[BOB]).status_code == 403
    )
    player = client.get(f"/api/v1/moderation/player/{BOB}", headers=sessions[OWNER]).json()
    assert player["capture_roles"] == ["reviewer"]


def test_daily_limit(capture):
    client, app, now, _, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    for _ in range(DAILY_LIMIT):
        assert location(client, mod).status_code == 200
    assert location(client, mod).status_code == 429
    now[0] += DAY
    assert location(client, mod).status_code == 200


def test_erasure_keeps_approved_work_without_a_name(capture):
    client, app, now, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    approved = submitted(client, mod)
    pending = submitted(client, mod, x=90.0)
    client.post(
        "/api/v1/moderation/captures/decide",
        headers=sessions[OWNER],
        json={"version": 1, "kind": "locations", "id": approved, "decision": "approve"},
    )
    erase = client.post(
        "/api/v1/auth/erase",
        headers=sessions[ALICE],
        json={"version": 1, "scope": "account", "confirmation": "DELETE"},
    )
    assert erase.status_code == 200, erase.text
    rows = {
        row["id"]: row
        for row in app.state.records.db.execute("SELECT id, uuid, name FROM capture_locations")
    }
    assert pending not in rows
    assert rows[approved]["uuid"] is None and rows[approved]["name"] is None
    assert app.state.moderation.capture_roles(ALICE) == []
    app.state.captures.cleanup()
    assert not app.state.captures.face_path(pending, 0).exists()
    assert app.state.captures.face_path(approved, 0).exists()


def test_rejected_submissions_are_cleaned_up_after_thirty_days(capture):
    client, app, now, sessions, grant, code = capture
    grant(ALICE)
    mod = code(ALICE)
    location_id = submitted(client, mod)
    client.post(
        "/api/v1/moderation/captures/decide",
        headers=sessions[OWNER],
        json={
            "version": 1,
            "kind": "locations",
            "id": location_id,
            "decision": "reject",
            "note": "blurry",
        },
    )
    app.state.captures.cleanup()
    assert app.state.captures.face_path(location_id, 0).exists()
    now[0] += 31 * DAY
    app.state.captures.cleanup()
    assert not app.state.captures.face_path(location_id, 0).exists()


def test_version_parsing_and_reencoding():
    assert version_tuple("0.1.0") == (0, 1, 0)
    assert version_tuple("1.2.3-beta") == (1, 2, 3)
    assert version_tuple(None) == (0, 0, 0)
    assert version_tuple("garbage") == (0, 0, 0)
    output = io.BytesIO()
    Image.new("P", (4, 4)).save(output, "PNG")
    with Image.open(io.BytesIO(reencode(output.getvalue(), 4, 4))) as image:
        assert image.mode == "RGBA"
