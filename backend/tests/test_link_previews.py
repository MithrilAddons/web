from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

import pytest
from mithril_web import link_previews
from mithril_web.auth import COOKIE
from mithril_web.run_maps import RunMap, retain_current
from mithril_web.run_preview import COLORS, coordinate, render_preview
from PIL import Image
from test_moderation import MOD, USER, post, seed
from test_moderation import setup as setup
from test_record_evidence_api import api as api
from test_run_maps import complete, map_data, timed_map


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.tags = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.tags[attrs.get("property", attrs.get("name"))] = attrs.get("content")


@pytest.fixture(autouse=True)
def template(monkeypatch):
    monkeypatch.setattr(link_previews, "INDEX", Path("frontend/index.html"))


def test_run_html_and_png_are_public_without_javascript(api):
    client, _, _, _, _ = api
    record = complete(api, timed_map())["record_id"]
    assert client.get(f"/runs/{record}", headers={"Host": "untrusted.invalid"}).status_code == 400
    response = client.get(f"/runs/{record}", headers={"X-Forwarded-Host": "untrusted.invalid"})
    assert response.status_code == 200
    tags = Metadata(response.text).tags
    assert "F7 solo clear · 0:15.000" in tags["og:title"]
    assert tags["og:url"] == f"https://mithril.foo/runs/{record}"
    assert tags["twitter:card"] == "summary_large_image"
    assert tags["og:image:width"] == "1200"
    assert tags["og:image:height"] == "630"
    assert tags["og:image:type"] == "image/png"
    assert "300 score" in tags["og:image:alt"]
    assert '<div id="root">' in response.text
    assert response.headers["cache-control"] == "no-store"
    image = client.get(tags["og:image"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.headers["cache-control"] == "no-store"
    with Image.open(BytesIO(image.content)) as png:
        assert png.size == (1200, 630)
        assert png.format == "PNG"
        x, y = coordinate(0)
        assert png.getpixel((x + 1, y + 1)) == (147, 108, 78)
    assert len(image.content) < 100_000
    for path in (f"/runs/{record}", tags["og:image"]):
        head = client.head(path)
        assert head.status_code == 200 and not head.content


def test_metadata_escapes_names_and_missing_name_uses_uuid(api):
    client, app, _, _, _ = api
    record = complete(api, map_data())["record_id"]
    with app.state.records.db:
        app.state.records.db.execute("UPDATE record_names SET name=?", ('<script>"&',))
    response = client.get(f"/runs/{record}")
    assert '<script>"&' not in response.text
    assert '<script>"&' in Metadata(response.text).tags["og:title"]
    with app.state.records.db:
        app.state.records.db.execute("DELETE FROM record_names")
    run = client.get(f"/api/v1/records/solo/{record}").json()
    assert run["record"]["uuid"] in Metadata(client.get(f"/runs/{record}").text).tags["og:title"]
    assert render_preview(run).startswith(b"\x89PNG")


def test_no_map_and_replaced_best_have_no_image(api):
    client, _, now, _, _ = api
    record = complete(api, map_data())["record_id"]
    now[0] += 1
    newer = complete(api, ticks=294)["record_id"]
    for record_id in (record, newer):
        html = client.get(f"/runs/{record_id}")
        assert html.status_code == 200
        tags = Metadata(html.text).tags
        assert "og:image" not in tags
        assert tags["twitter:card"] == "summary"
        assert client.get(f"/api/v1/records/solo/{record_id}/preview.png").status_code == 404


@pytest.mark.parametrize("record_id", ["invalid", "a" * 43])
def test_missing_run_does_not_advertise_a_map(api, record_id):
    client = api[0]
    response = client.get(f"/runs/{record_id}")
    assert response.status_code == 404
    tags = Metadata(response.text).tags
    assert tags["og:title"] == "Run unavailable · Mithril"
    assert "og:image" not in tags
    assert client.get(f"/api/v1/records/solo/{record_id}/preview.png").status_code == 404


def test_erasure_removes_both_previews(api):
    client, _, _, _, session = api
    record = complete(api, map_data())["record_id"]
    client.cookies.set(COOKIE, session)
    assert (
        client.post(
            "/api/v1/auth/erase",
            headers={"Origin": "https://mithril.foo"},
            json=dict(version=1, scope="records", confirmation="DELETE"),
        ).status_code
        == 200
    )
    assert client.get(f"/runs/{record}").status_code == 404
    assert client.get(f"/api/v1/records/solo/{record}/preview.png").status_code == 404


def test_ban_hides_previews(setup):
    client, app, _, headers, _ = setup
    record = seed(app)
    with app.state.records.db:
        retain_current(app.state.records.db, USER, "F7", record, RunMap.model_validate(map_data()))
    assert client.get(f"/api/v1/records/solo/{record}/preview.png").status_code == 200
    assert post(client, headers[MOD], "sanction", uuid=USER, kind="ban").status_code == 200
    assert client.get(f"/runs/{record}").status_code == 404
    assert client.get(f"/api/v1/records/solo/{record}/preview.png").status_code == 404


def test_preview_errors_do_not_return_a_misleading_image(api, monkeypatch, tmp_path):
    client, app, _, _, _ = api
    record = complete(api, map_data())["record_id"]
    monkeypatch.setattr(link_previews, "INDEX", tmp_path / "missing.html")
    assert client.get(f"/runs/{record}").status_code == 503
    with app.state.records.db:
        app.state.records.db.execute("UPDATE pb_maps SET data=?", (b"",))
    assert client.get(f"/runs/{record}").status_code == 503
    assert client.get(f"/api/v1/records/solo/{record}/preview.png").status_code == 503


def test_map_shapes_connections_statuses_and_unknown_counts():
    data = map_data()
    data["rooms"][0].update(tiles=[0, 1, 6, 7], secrets_found=None, secrets_total=None)
    data["rooms"][1].update(tiles=[2], state="FAILED")
    data["doors"] = [dict(a=1, b=2, type="WITHER")]
    run = dict(record=dict(name=None, uuid="a" * 32, ticks=144000, floor="M7"), map=data)
    with Image.open(BytesIO(render_preview(run))) as png:
        x, y = coordinate(0)
        assert png.getpixel((x + 63, y + 63)) == (147, 108, 78)
        assert png.getpixel((x + 56, y + 20)) == (147, 108, 78)
        assert png.getpixel((x + 20, y + 63)) == (147, 108, 78)
        assert png.getpixel((x + 133, y + 28)) == (214, 180, 232)
    for kind in [*COLORS, "UNKNOWN"]:
        data["rooms"][0].update(type=kind, state="UNOPENED")
        assert render_preview(run).startswith(b"\x89PNG")


def test_generic_preview_describes_the_site():
    tags = Metadata(Path("frontend/index.html").read_text(encoding="utf-8")).tags
    assert tags["og:title"] == "Mithril · Hypixel SkyBlock"
    assert "dungeon replays" in tags["og:description"]
