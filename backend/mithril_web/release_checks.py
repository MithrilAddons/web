"""Optional release-workflow metrics carried in a hidden GitHub notes comment."""

import json
import re

MARKER = re.compile(r"<!--\s*mithrilpf-checks:(.*?)-->", re.DOTALL)


def extract_checks(notes, version, digest):
    matches = MARKER.findall(notes)
    cleaned = MARKER.sub("", notes).strip()
    if len(matches) != 1 or len(matches[0]) > 2048:
        return cleaned, None
    try:
        value = json.loads(matches[0])
        if (
            value["version"] != 1
            or value["mod_version"] != version
            or value["sha256"] != digest
            or type(value["run_id"]) is not int
            or not 0 < value["run_id"] < 10**15
            or type(value["tests"]) is not int
            or not 0 < value["tests"] <= 1_000_000
        ):
            raise ValueError("Invalid release checks")
        result = {
            "tests": value["tests"],
            "run_url": f"https://github.com/MithrilAddons/mithrilpf/actions/runs/{value['run_id']}",
        }
        for kind in ("line", "branch"):
            covered, total = value[kind]["covered"], value[kind]["total"]
            if (
                type(covered) is not int
                or type(total) is not int
                or not 0 <= covered <= total <= 10_000_000
                or total == 0
            ):
                raise ValueError("Invalid coverage")
            result[f"{kind}_coverage"] = round(covered * 100 / total, 1)
        return cleaned, result
    except (ValueError, TypeError, KeyError):
        return cleaned, None
