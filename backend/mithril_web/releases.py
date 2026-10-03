"""Public release metadata only; JAR downloads go directly to GitHub."""

import http.client
import json
import re
import threading
import time

RELEASES_URL = "https://github.com/MithrilAddons/mithrilpf/releases"
MAX_RESPONSE = 131072
VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?")


def parse_release(value):
    if (
        not isinstance(value, dict)
        or value.get("draft") is not False
        or not isinstance(value.get("prerelease"), bool)
    ):
        raise ValueError("Expected a published release")
    tag = value.get("tag_name")
    match = VERSION.fullmatch(tag) if isinstance(tag, str) else None
    if not match or value["prerelease"] != bool(match[4]):
        raise ValueError("Invalid version")
    name = f"mithrilpf-{tag[1:]}.jar"
    assets = value.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Missing assets")
    url = f"{RELEASES_URL}/download/{tag}/{name}"
    if not any(
        isinstance(asset, dict)
        and asset.get("name") == name
        and asset.get("state") == "uploaded"
        and asset.get("browser_download_url") == url
        for asset in assets
    ):
        raise ValueError("Release JAR missing")
    return {"version": tag[1:], "url": url}


def select_release(values):
    """Highest supported version among the ten recent published releases, including betas."""
    if not isinstance(values, list) or len(values) > 10:
        raise ValueError("Invalid release list")
    candidates = []
    for value in values:
        try:
            release = parse_release(value)
        except ValueError:
            continue
        match = VERSION.fullmatch("v" + release["version"])
        rank = {"alpha": 0, "beta": 1, "rc": 2, None: 3}[match[4]]
        key = (*map(int, match.group(1, 2, 3)), rank, int(match[5] or 0))
        candidates.append((key, release))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def fetch_release_catalog():
    connection = http.client.HTTPSConnection("api.github.com", timeout=4)
    try:
        connection.request(
            "GET",
            "/repos/MithrilAddons/mithrilpf/releases?per_page=10",
            headers={
                "User-Agent": "MithrilPF-Web",
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        if response.status == 404:
            return []
        if (
            response.status != 200
            or response.getheader("Content-Encoding", "identity") != "identity"
        ):
            raise ValueError("Release unavailable")
        data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("Release response too large")
        values = json.loads(data)
        select_release(values)  # Validate the bounded catalogue before caching it.
        return values
    finally:
        connection.close()


def fetch_release():
    return select_release(fetch_release_catalog())


def discord_release(value):
    """Only announce an uploaded official JAR with GitHub's SHA-256 digest."""
    release = parse_release(value)
    if len(release["version"]) > 80:
        raise ValueError("Version too long for announcement")
    asset = next(
        a
        for a in value["assets"]
        if isinstance(a, dict) and a.get("browser_download_url") == release["url"]
    )
    digest = asset.get("digest", "")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        raise ValueError("Missing SHA-256")
    notes = value.get("body") or ""
    if not isinstance(notes, str):
        raise ValueError("Invalid release notes")
    return {
        **release,
        "prerelease": value["prerelease"],
        "sha256": digest[7:].lower(),
        "notes": notes[:3000],
        "page": f"{RELEASES_URL}/tag/v{release['version']}",
        "modrinth": "https://modrinth.com/mod/mithrilpf",
    }


class ReleaseCache:
    """One refresh at a time, five-minute cache, one-minute backoff on failure."""

    def __init__(self, loader=None, clock=time.monotonic):
        self.loader = loader
        self.clock = clock
        self.lock = threading.Lock()
        self.expires = 0
        self.value = {"status": "unavailable", "release": None}
        self.discord_value = {
            "version": 1,
            "status": "unavailable",
            "updated_at": None,
            "releases": [],
        }

    def get(self):
        if not self.lock.acquire(blocking=False):
            return self.value
        try:
            if self.clock() >= self.expires:
                try:
                    catalog = []
                    if self.loader is None:
                        values = fetch_release_catalog()
                        release = select_release(values)
                        details = []
                        for value in values:
                            try:
                                details.append(discord_release(value))
                            except (ValueError, StopIteration):
                                continue
                        # Keep the highest supported version first, matching the public link.
                        catalog = sorted(
                            details,
                            key=lambda item: _version_key(item["version"]),
                            reverse=True,
                        )
                    else:
                        release = self.loader()
                    self.value = {"status": "ready" if release else "none", "release": release}
                    self.discord_value = {
                        "version": 1,
                        "status": "ready",
                        "updated_at": time.time(),
                        "releases": catalog,
                    }
                    self.expires = self.clock() + 300
                except (OSError, ValueError, http.client.HTTPException):
                    # A temporary GitHub failure must not discard a known good link.
                    self.expires = self.clock() + 60
                    self.discord_value = {
                        **self.discord_value,
                        "status": "stale"
                        if self.discord_value["updated_at"] is not None
                        else "unavailable",
                    }
            return self.value
        finally:
            self.lock.release()

    def discord(self):
        self.get()
        return self.discord_value


def _version_key(version):
    match = VERSION.fullmatch("v" + version)
    return (
        *map(int, match.group(1, 2, 3)),
        {"alpha": 0, "beta": 1, "rc": 2, None: 3}[match[4]],
        int(match[5] or 0),
    )
