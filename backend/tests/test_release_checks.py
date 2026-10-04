import copy
import json

import pytest
from mithril_web.release_checks import extract_checks
from mithril_web.releases import discord_release
from test_discord_api import RELEASE

CHECKS = {
    "version": 1,
    "mod_version": "1.2.3",
    "run_id": 123,
    "tests": 42,
    "sha256": "b" * 64,
    "line": {"covered": 80, "total": 100},
    "branch": {"covered": 3, "total": 4},
}


def comment(value):
    return "Notes\n\n<!-- mithrilpf-checks:" + json.dumps(value) + " -->"


def test_metrics_are_bound_to_release_and_removed_from_notes():
    value = discord_release({**RELEASE, "body": comment(CHECKS)})
    assert value["notes"] == "Notes"
    assert value["checks"] == {
        "tests": 42,
        "line_coverage": 80.0,
        "branch_coverage": 75.0,
        "run_url": "https://github.com/MithrilAddons/mithrilpf/actions/runs/123",
    }
    assert "checks" not in discord_release(RELEASE)


@pytest.mark.parametrize(
    "key,bad",
    [
        ("version", 2),
        ("mod_version", "9.9.9"),
        ("sha256", "a" * 64),
        ("run_id", True),
        ("run_id", -1),
        ("tests", True),
        ("tests", 0),
        ("line", {"covered": True, "total": 100}),
        ("line", {"covered": 1, "total": 0}),
        ("branch", {"covered": 11, "total": 10}),
        ("branch", {"covered": 1, "total": "10"}),
    ],
)
def test_invalid_metrics_never_suppress_release_or_claim_a_pass(key, bad):
    value = copy.deepcopy(CHECKS)
    value[key] = bad
    release = discord_release({**RELEASE, "body": comment(value)})
    assert release["notes"] == "Notes"
    assert "checks" not in release


@pytest.mark.parametrize("raw", ["{}", "null", "[]", "not json", "x" * 2049])
def test_malformed_or_oversized_metadata_is_omitted(raw):
    notes, checks = extract_checks("Notes<!-- mithrilpf-checks:" + raw + " -->", "1.2.3", "b" * 64)
    assert notes == "Notes"
    assert checks is None


def test_duplicate_metadata_is_not_accepted():
    assert extract_checks(comment(CHECKS) + comment(CHECKS), "1.2.3", "b" * 64)[1] is None
