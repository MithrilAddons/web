# API v1

All production requests use `https://mithril.foo/api/v1`. Responses and explicitly
versioned request bodies use `version: 1`. Synthetic fixtures live in `contracts/`;
Python and frontend tests check their meanings. No real accounts belong in fixtures.

## Account linking and scoped mod credentials

The user starts linking in Minecraft. `POST auth/challenge` accepts `{version,
uuid, name}`: UUID is 32 lowercase hexadecimal characters; name is 1–16 ASCII
letters, digits or underscores. It returns a 43-character URL-safe `challenge_id`,
39-hex-character `server_id` and 60-second lifetime. Minecraft proves ownership
through Mojang's `joinServer`. **Only Mojang receives the Minecraft access token.**
`POST auth/verify` consumes `{challenge_id}` once and checks Mojang `hasJoined`.
The reply contains `link_token`, `receipt_token` and a 300-second lifetime.

The mod opens `https://mithril.foo/link#<link_token>`. The browser removes the
fragment, previews the account with `POST auth/preview {token}`, and explicitly
confirms it with `POST auth/complete {token, remember}`. Confirmation consumes the
link and replaces this browser's previous session. `GET auth/session` returns
`{authenticated, user?: {uuid, name}}`; `POST auth/logout` revokes the session.
Browser mutations require the exact production Origin. Cookies are Secure,
HttpOnly, SameSite=Strict, host-only; see the public `/cookies` page. Remembered
sessions expire after 30 days, renewed on session checks at most daily; otherwise
they expire after 24 hours. Anonymous browsing sets no cookie.

The mod stores only the status receipt per UUID. `POST auth/link-status {token}`
returns `pending`, `expired` or `linked` with the user identity. A receipt cannot
log in, renew a browser session or authorize uploads/party actions by itself.

## Player card

`GET auth/player-card` requires a browser session and derives identity from it.
It returns selected-profile Catacombs level, secrets, highest recorded magical
power, and S+ PBs for F1–F7/M1–M7. Missing values are null, not zero.
The mod-record fields are reserved and empty until syncing is implemented.
See the shared synthetic `contracts/player-card-v1.json` fixture.

`GET auth/skin` serves a validated Mojang skin for the signed-in account. Arbitrary
URLs and redirects are rejected; licenses ship in /skin-viewer-licenses.txt.

Hypixel responses are bounded at 16 MiB with fixed destinations and socket timeouts.
Player summaries are cached for five minutes, at most 128 accounts, two in-flight
fetches and 30 attempts per minute. Failed lookups back off. API keys stay on the
server and must never appear in browser code, logs, fixtures or source control.
