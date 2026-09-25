from tools.check_branch_name import valid


def test_valid_branches():
    for prefix in ("feat", "fix", "chore", "refactor", "docs"):
        assert valid(f"{prefix}/web-foundation")


def test_invalid_branches():
    for name in ("main", "feat/Test", "feat/-test", "feat/a--b", "feat/a_b", "feat/a/b", ""):
        assert not valid(name)


def test_dependabot_exception_requires_bot_author():
    assert valid("dependabot/npm/test", "dependabot[bot]")
    assert not valid("dependabot/npm/test", "someone")
