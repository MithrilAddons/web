# Development

This repository contains the MithrilPF website and its web API. The Minecraft
mod lives separately in MithrilAddons/mithrilpf. React/TypeScript handles browser
UI; FastAPI leaves a straightforward migration path for the existing Python
matching prototype. They share one origin, not separate public API domains.

## Setup

Use Node.js 24.15.0 (or a newer 24.x patch), Python 3.12–3.14, and uv 0.12.19.
Dependencies are exact-pinned with npm and uv lockfiles. Do not use global app
dependencies. On Windows, `npm.cmd` works when PowerShell blocks `npm.ps1`.

```text
npm ci --ignore-scripts
uv sync --locked
python tools/dev.py
```

If uv is not installed, create a tooling environment with `python -m venv .tools`
and install `uv==0.12.19` into it. On Windows its executable is
`.tools/Scripts/uv.exe`; on Linux it is `.tools/bin/uv`. The check script also
recognizes this isolated installation.

Open http://127.0.0.1:5173. Vite forwards `/api` to the loopback backend on port 8000. Ctrl+C stops both processes. Frontend edits update automatically; restart
the command after backend edits. Neither development server is exposed publicly.

The root page links to `/party-finder`, where the party-finder UI lives. Navigation
uses normal links; the dev server and nginx both serve the app on direct route loads.
Account linking is documented in docs/ACCOUNT_LINKING.md; `/cookies` describes
the actual session cookies. Local anonymous UI works over HTTP, but sign-in uses
production HTTPS only. Use the isolated backend/frontend tests for synthetic auth.

## Checks and formatting

```text
npm run format
uv run --locked ruff check --fix .
uv run --locked ruff format .
python tools/check.py
```

The check script checks the Python lockfile, Ruff lint/format, Python tests,
Prettier, ESLint, frontend tests, TypeScript, and the production frontend build.
Install dependencies first; checks do not intentionally fetch external data.
Tests use synthetic data only and never connect to Minecraft, Hypixel, or an account.
The shared health fixture is checked by both client and server tests.

CI runs this same command on Ubuntu/Python 3.12 and Windows/Python 3.14. PRs get
one two-platform run; main is checked again after merging. Dependencies do not
run npm install scripts. No workflow deploys or receives production secrets.
Required check names, once these jobs have run, are `Verify (ubuntu-24.04)` and
`Verify (windows-2025)`.
PR branch names must use feat/, fix/, chore/, refactor/, or docs/ with a kebab-case
description; Dependabot-authored dependabot/ branches are exempt. Both platforms
upload test reports and the tested frontend build for 14 days. Reports also appear
locally in `build/reports/`, which is ignored by Git.

Manually check the landing page at desktop and narrow widths, confirm its service
state, then stop the backend and reload to check the unavailable state. Build and
unit tests do not replace browser or deployment testing.

## Contribution boundaries

Use short `feat/`, `fix/`, `chore/`, `refactor/`, or `docs/` branches, signed commits,
and focused PRs. Explain behavior changes and tests. Dependency updates must update
the relevant lockfile and pass both platforms. No license has been selected yet;
do not assume permission to redistribute third-party code or copy old assets.
