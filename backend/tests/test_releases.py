import copy
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from mithril_web.app import create_app
from mithril_web.releases import (
    MAX_RESPONSE,
    ReleaseCache,
    fetch_release,
    parse_release,
    select_release,
)

URL = "https://github.com/MithrilAddons/mithrilpf/releases/download/v1.2.3/mithrilpf-1.2.3.jar"
RELEASE = {
    "tag_name": "v1.2.3",
    "draft": False,
    "prerelease": False,
    "assets": [{"name": "mithrilpf-1.2.3.jar", "state": "uploaded", "browser_download_url": URL}],
}


def test_exact_jar_not_sources_or_checksums():
    value = copy.deepcopy(RELEASE)
    value["assets"].insert(0, {"name": "mithrilpf-1.2.3-sources.jar"})
    assert parse_release(value) == {"version": "1.2.3", "url": URL}


@pytest.mark.parametrize(
    "patch",
    [
        {"draft": True},
        {"prerelease": True},
        {"tag_name": "../other"},
        {"assets": []},
        {"assets": None},
        {
            "assets": [
                {
                    "name": "mithrilpf-1.2.3.jar",
                    "state": "uploaded",
                    "browser_download_url": "https://evil.invalid/mod.jar",
                }
            ]
        },
    ],
)
def test_invalid_releases(patch):
    with pytest.raises(ValueError):
        parse_release({**RELEASE, **patch})


@pytest.mark.parametrize(
    "status,data,expected",
    [
        (200, json.dumps([RELEASE]).encode(), "ready"),
        (404, b"", "none"),
        (429, b"", "error"),
        (500, b"", "error"),
        (200, b"{bad json", "error"),
        (200, b"x" * (MAX_RESPONSE + 1), "error"),
    ],
    ids=["success", "missing", "rate-limit", "server-error", "malformed", "oversized"],
)
def test_bounded_http_and_cleanup(monkeypatch, status, data, expected):
    connection = Mock()
    response = connection.getresponse.return_value
    response.status = status
    response.getheader.return_value = "identity"
    response.read.return_value = data
    factory = Mock(return_value=connection)
    monkeypatch.setattr("mithril_web.releases.http.client.HTTPSConnection", factory)
    if expected == "error":
        with pytest.raises(ValueError):
            fetch_release()
    else:
        assert fetch_release() == (parse_release(RELEASE) if expected == "ready" else None)
    factory.assert_called_once_with("api.github.com", timeout=4)
    connection.close.assert_called_once()
    assert (
        connection.request.call_args.args[1]
        == "/repos/MithrilAddons/mithrilpf/releases?per_page=10"
    )
    if status == 200:
        response.read.assert_called_once_with(MAX_RESPONSE + 1)


def release_fixture(version):
    name = f"mithrilpf-{version}.jar"
    url = f"https://github.com/MithrilAddons/mithrilpf/releases/download/v{version}/{name}"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": "-" in version,
        "assets": [{"name": name, "state": "uploaded", "browser_download_url": url}],
    }


def test_beta_selection_and_semantic_order_not_api_order():
    versions = ["0.2.0-rc.2", "0.2.0-beta.10", "0.2.0-rc.3", "0.1.0", "0.2.0-alpha.1"]
    assert select_release([release_fixture(v) for v in versions])["version"] == "0.2.0-rc.3"
    assert (
        select_release([release_fixture("0.2.0-rc.99"), release_fixture("0.2.0")])["version"]
        == "0.2.0"
    )
    assert (
        select_release([release_fixture("0.2.0-beta.2"), release_fixture("0.2.0-beta.10")])[
            "version"
        ]
        == "0.2.0-beta.10"
    )


def test_selection_skips_drafts_missing_assets_and_unsupported_tags():
    good = release_fixture("0.2.0-rc.3")
    assert select_release(
        [
            {**release_fixture("9.0.0"), "draft": True},
            {**release_fixture("8.0.0"), "assets": []},
            release_fixture("7.0.0-nightly.1"),
            good,
        ]
    ) == parse_release(good)
    assert select_release([]) is None
    assert select_release([{**good, "prerelease": False}]) is None
    for invalid in ({}, None, [good] * 11):
        with pytest.raises(ValueError):
            select_release(invalid)


def test_cache_refresh_and_failure_backoff():
    now = [100]
    loader = Mock(side_effect=[parse_release(RELEASE), OSError("offline"), None])
    cache = ReleaseCache(loader, clock=lambda: now[0])
    first = cache.get()
    assert first["status"] == "ready"
    now[0] += 299
    assert cache.get() == first
    assert loader.call_count == 1
    now[0] += 1
    assert cache.get() == first
    now[0] += 59
    assert cache.get() == first
    assert loader.call_count == 2
    now[0] += 1
    assert cache.get() == {"status": "none", "release": None}


def test_parallel_refresh_does_not_queue_network_calls():
    loader = Mock(return_value=None)
    cache = ReleaseCache(loader)
    with cache.lock:
        assert cache.get()["status"] == "unavailable"
    loader.assert_not_called()


def test_public_read_only_endpoint(tmp_path):
    with TestClient(
        create_app(database=tmp_path / "auth.db", release_loader=lambda: parse_release(RELEASE)),
        base_url="http://localhost",
    ) as client:
        response = client.get("/api/v1/mod-release")
        assert response.status_code == 200
        assert response.json() == {"status": "ready", "release": {"version": "1.2.3", "url": URL}}
        assert client.post("/api/v1/mod-release").status_code == 405
