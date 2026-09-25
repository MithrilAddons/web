"""Validate PR branch names without interpolating untrusted refs into a shell."""

import os
import re
import sys

PATTERN = re.compile(r"(?:feat|fix|chore|refactor|docs)/[a-z0-9]+(?:-[a-z0-9]+)*")


def valid(name, author=""):
    return bool(PATTERN.fullmatch(name)) or (
        author == "dependabot[bot]" and name.startswith("dependabot/")
    )


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PR_HEAD_REF", "")
    if not valid(name, os.environ.get("PR_AUTHOR", "")):
        raise SystemExit("Use feat/, fix/, chore/, refactor/, or docs/ plus a kebab-case name.")
