# Development

React/TypeScript frontend and FastAPI backend for MithrilPF, served from one origin.
The Minecraft client lives separately in MithrilAddons/mithrilpf.

## Setup

Use Node.js 24.15.0 or a newer 24.x patch, Python 3.12–3.14, and uv 0.12.19.
Dependencies are exact-pinned. On Windows use `npm.cmd` if PowerShell blocks npm.

```text
npm ci --ignore-scripts
uv sync --locked
python tools/dev.py
```

An isolated uv installation in `.tools/Scripts/uv.exe` or `.tools/bin/uv` is also
supported. The frontend is at http://127.0.0.1:5173 and forwards /api to the
loopback backend. Ctrl+C stops both. Local sign-in must use synthetic test fixtures,
not real production credentials. See [API.md](API.md) and [DEPLOYMENT.md](DEPLOYMENT.md).

## Checks and contributions

```text
npm run format
uv run --locked ruff check .
uv run --locked ruff format .
python tools/check.py
```

The check script validates the lockfile, Ruff, Python tests, Prettier, ESLint,
frontend tests, TypeScript and the production build. Tests use synthetic data only;
they never contact Minecraft/Hypixel or read real accounts. Shared payload fixtures
live in `contracts/`. Python/backend code lives in `backend/`, UI in `frontend/src/`.

CI runs the same checks on Ubuntu/Python 3.12 and Windows/Python 3.14. Required jobs
are `Verify (ubuntu-24.04)` and `Verify (windows-2025)`. Workflows have read-only
permissions and no production credentials; they do not deploy. Reports/builds are
retained for 14 days; local reports are under ignored `build/reports/`.

Use focused `feat/`, `fix/`, `chore/`, `refactor/` or `docs/` branches, signed
commits and PRs. Preserve protocol compatibility and optional-mod independence.
Do not put secrets, account data or runtime files in fixtures or commits.
Only this guide, the API contract and deployment guide are public documentation;
working plans, design notes, agent files and verification journals stay local.
No project license has been selected; preserve all third-party notices.

## Manual verification

Build first, then run `python tools/preview_skin.py` or
`python tools/preview_party.py` for loopback previews with synthetic accounts.
Check desktop/narrow layouts, keyboard focus, skin rotation, player-card dialogs,
form inputs and service failures. Test party creation, eligible class selection,
restored floor selection and full/invited states. Live Minecraft handoff checks
are in API.md. Automated tests do not establish live-game correctness.
