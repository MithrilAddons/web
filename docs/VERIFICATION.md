# Foundation verification — 2026-09-25

## Persistent mod link status — 2026-09-25

- Full web checks passed: 41 backend tests, 25 frontend tests, lock consistency,
  Ruff, Prettier, ESLint, TypeScript and production build. Existing Starlette
  deprecation and lazy renderer chunk-size warnings remain.
- Receipt tests cover pending/confirmed status, expiry, renewal, logout/replacement,
  restart persistence, hashing, origin rejection and inability to use a receipt
  as a browser login credential. Tests use synthetic accounts and temporary stores.
- Deployed `link-memory-20260925`; health/pages passed and an unknown synthetic
  receipt returned expired. Existing browser sessions remain; no schema migration.
- MithrilPF full checks passed: 16 JVM tests, four tooling tests, formatting,
  build and packaged-JAR validation. Practice JAR backed up, replaced and hashes matched.
- Actual Minecraft/browser confirmation and restart persistence need user testing.
  Existing users must link once more for the new receipt. No commit or push.

## Copy cleanup — 2026-09-25

- Removed visible skin instructions/reset button, redundant heading labels and
  landing-page subtitle. The landing heading is now simply Party Finder.
- Full `python tools/check.py` passed: 37 backend and 25 frontend tests, formatting,
  lint, TypeScript and build. Existing dependency/build warnings are unchanged.
- Deployed frontend-only release `copy-cleanup-20260925`; backend and sessions
  unchanged. Browser-checked live landing and anonymous party-finder navigation.
  Signed-in controls are covered by regression tests, not repeated live sign-in.
- No commit or push performed.

## Account skin preview — 2026-09-25

- Full `python tools/check.py` passed on Windows: 37 backend and 25 frontend
  tests, lock consistency, Ruff, Prettier, ESLint, TypeScript and production build.
- Browser-tested the production bundle with a synthetic skin through
  `tools/preview_skin.py`: model rendering, drag rotation, wheel zoom, reset and
  keyboard rotation work. This harness uses no real accounts or shared cookies.
- No browser errors captured. Three.js emits a graphics-driver shader-bias
  clamping warning on this machine; rendering works. Vite warns about the 516 KB
  renderer chunk (129 KB compressed), which is lazy-loaded only for signed-in
  accounts. The existing Starlette TestClient deprecation warning remains.
- Deployed `skin-preview-20260925`, retaining the previous release for rollback.
  Restarted only mithril-web; session storage and nginx configuration unchanged.
  Live health, party-finder and license notice return 200; anonymous skin requests
  return 401. The live anonymous account card still renders correctly.
- Real-account skin fetching/rendering still needs the owner's signed-in browser
  check. No mobile-device hardware test, hosted CI, Git commit or push performed.

## Visual refresh — 2026-09-25

- Full `python tools/check.py` passed: 21 Python and 20 frontend tests, lockfile,
  lint/format, TypeScript and production build. No dependency/backend changes.
- Inspected Linear and Stripe as visual references; implemented original styling
  using local/system fonts, restrained charcoal/periwinkle colors and responsive layout.
- Browser checks: desktop home/workspace; narrow home/workspace with no horizontal
  overflow. Checked live home navigation, service status and anonymous account panel.
- Deployed frontend as `visual-refresh-20260925`, retaining the prior release.
  Backend process, nginx configuration and session database were left unchanged.
- No real-account sign-in repeated, mobile-device hardware test or hosted CI run.
  Authentication regression tests still pass; actual end-to-end login remains a
  separate manual acceptance check. No Git commit or push.

## Account-linking update — 2026-09-25

- Full `python tools/check.py` passed on Windows: 21 Python tests and 18 frontend
  tests, lock verification, lint/format, TypeScript, and production build.
- An initial frontend run failed three legacy health tests because their fetch
  mock reused one Response for both health and account requests. Fixtures now
  route by endpoint and return separate responses; the complete rerun passed.
- MithrilPF companion repository passed its full check: eight JVM tests, four
  tooling tests, formatting, build, wrapper and packaged-JAR checks.
- Deployed `account-linking-20260925`; previous release retained for rollback.
  Auth storage is outside releases, owned by mithril-web (directory 0700/file 0600).
- Live health/session/cookies/link URLs return 200 with no anonymous Set-Cookie.
  Cross-origin preview returns 403. Nginx configuration validation passed.
- Browser inspection confirmed party-finder instructions, cookie-policy layout,
  and expired-link handling; the fragment was removed from the address bar.
- Existing Atlas API still returns 200; Atlas and relay services remain active.
- Practice-instance JAR replaced after backup, with matching build/install SHA-256.
- Not yet verified: actual licensed Minecraft/Mojang sign-in, browser persistence
  after real sign-in, in-game UI/cancellation, Linux full tests, mobile layout, or
  hosted GitHub CI. These need manual testing; compilation is not live verification.
- No source committed or pushed; AGENTS.md remains locally excluded in both repos.

The sections below record the earlier health-only foundation, before this update.

## Passed locally (Windows)

- `python tools/check.py`: uv lock consistency, Ruff lint/format, Prettier,
  ESLint, TypeScript checking, and production Vite build.
- Python 3.14.5: eight backend tests.
- Node 24.15.0: nine frontend tests.
- `npm install --ignore-scripts`: zero known vulnerabilities reported by npm audit.
- Local launcher: frontend and backend start together, health reaches the browser,
  and Ctrl+C releases both listening ports.
- Desktop browser: live page renders correctly and reports the service online;
  no captured browser warnings/errors.

The initial build found a missing Vite CSS type declaration; it was added and the
entire check suite then passed. Backend tests currently emit an upstream
Starlette deprecation warning about its httpx TestClient adapter.

An extra Windows Python 3.12 test attempt could not run: uv's interpreter download
reported a missing target directory. The existing Python installation was not
modified to work around it. The Linux deployment does run on Python 3.12.3, but
that health check is not equivalent to running its full test suite.

## Passed on the deployment

- Authoritative DNS: root A resolves to the server; www CNAME resolves to the root.
- Root HTTPS 200, www HTTPS redirect, health JSON 200, unknown API route 404.
- Valid certificate covers both names; Certbot renewal dry run succeeds and its
  renewal timer is enabled. The existing nginx renewal hook validates and reloads nginx.
- Dedicated unprivileged service active, listening only on loopback port 8780.
- Existing Atlas API root and relay health endpoint still respond successfully.

## Not yet verified

- GitHub Actions on either hosted runner: nothing has been committed/pushed.
- Full Linux test suite and browser checks on mobile/narrow-screen devices.
- Party matching, account linking, mod communication, persistence, or player data:
  these are not implemented in this foundation.
