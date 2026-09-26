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
The reply contains `link_token`, `receipt_token`, `user_code` (`ABCD-EFGH` format)
and a 300-second lifetime. Existing long-token clients remain supported.

The mod opens `https://mithril.foo/link#<link_token>`. The browser removes the
fragment, previews the account with `POST auth/preview {token}`, and explicitly
confirms it with `POST auth/complete {token, remember}`. Confirmation consumes the
link and replaces this browser's previous session. `GET auth/session` returns
`{authenticated, user?: {uuid, name}}`; `POST auth/logout` revokes the session.
Browser mutations require the exact production Origin. Cookies are Secure,
HttpOnly, SameSite=Strict, host-only; see the public `/cookies` page. Remembered
sessions expire after 30 days, renewed on session checks at most daily; otherwise
they expire after 24 hours. Anonymous browsing sets no cookie.

The mod can also copy that link or encode it locally as a QR. `/link` without a
fragment accepts the short code; preview/complete accept it in the same `token`
field (case-insensitive, optional hyphen). Both spellings redeem the same link
atomically. Short codes and links are hashed at rest, share the five-minute expiry,
and cannot be reused after either is confirmed. Short-code preview/completion share
a 10-attempt/client/minute and 100-attempt/global/minute in-process limit in addition
to proxy limits. No code or token belongs in access logs or analytics. Multiple
backend workers would require a shared guessing-limit store before deployment.
The mod retains its previous receipt until the new browser is confirmed; starting
or abandoning another attempt does not invalidate existing browser sessions.

The mod stores only the status receipt per UUID. `POST auth/link-status {token}`
returns `pending`, `expired` or `linked` with the user identity. A receipt cannot
log in, renew a browser session or authorize uploads/party actions by itself.

Two separate scopes require a linked receipt and another fresh Mojang proof:

| Scope   | Challenge / verification                    | Credential    | Lifetime   | Permitted use       |
| ------- | ------------------------------------------- | ------------- | ---------- | ------------------- |
| Records | `auth/sync-challenge`, `auth/sync-verify`   | `sync_token`  | 15 minutes | `auth/sync-records` |
| Parties | `auth/party-challenge`, `auth/party-verify` | `party_token` | 30 days    | `party/mod/*`       |

Both challenges accept `{version, uuid, name, receipt_token}`. Both verifications
accept `{challenge_id, receipt_token}` and return `{version, user, <scope>_token,
expires_in_seconds}`. Use `Authorization: Bearer <token>` for scoped operations.
Each verification consumes its own kind of challenge. A fresh party proof replaces
the previous party credential for that browser link. The client renews automatically
through another proof; no repeated browser interaction is needed while linked.

Credentials are random, stored hashed on the backend, and held only in mod memory.
They cannot log into the browser or cross scopes. Every scoped request rechecks
its parent browser session: logout, replacement or expiry revokes access. Mod routes
reject Origin headers, but that check is not a substitute for authentication.
Proofs are serialized inside the mod so concurrent linking/syncing cannot overwrite
one another's Mojang server proof. No dev-account bypass or custom URI installer exists.

## Account card and records

`GET auth/player-card` derives the UUID from the browser session. It returns selected
Hypixel profile data (not merged profiles): Catacombs XP/level, secrets, highest recorded
magical power, and S+ PBs for F1–F7/M1–M7. Missing values are null. Account-wide mod
records are shown separately; SS is not collected yet. See `player-card-v1.json`.
Catacombs and all five dungeon class levels include fractional overflow above 50
at 200,000,000 XP per level.

`POST auth/sync-records` accepts `mod-records-v1.json`: at most four unique `(floor,
kind)` pairs, F7/M7 and `solo_clear`/`terminals`, positive real milliseconds and ticks,
bounded at two hours. The backend transaction merges independent minimums; repeated
or slower uploads cannot overwrite bests. These are client-reported records, not
proof of gameplay. Room records/full run history are not uploaded. Browser logout
does not delete records. Records persist in `records.sqlite3` alongside auth storage.

`GET auth/skin` serves a validated Mojang skin for the signed-in UUID; arbitrary
URLs/redirects are rejected. The lazy skin renderer's licenses ship in
`/skin-viewer-licenses.txt`. No analytics or third-party browser skin requests.

Hypixel responses are bounded at 16 MiB with fixed destinations and socket timeouts.
The player-card cache (five minutes, 128 accounts) and matching cache (six hours,
4000 accounts) currently have **separate** limits of two in-flight / 30 attempts per
minute each, not a shared global budget. Failed lookups back off. API keys stay on
the server; cache misses must not fabricate qualifying stats.

## Party finder

Website routes under `party/` require the browser session. POST mutations and
`state` also require the exact production Origin. Strict bodies reject unknown
fields. `party-v1.json` shows matching, listings, personal state and rule shapes.

- `POST state {version, known?, state_id?}`: personal state and notices. Held up to
  25 seconds when unchanged; also records website presence. Always echo both revision
  and state ID. IDs change after server restart/player recreation: accept a new ID
  even with a lower revision; reject late responses from retired IDs.
- `POST look {version, floor, classes, max_team_s_plus_ms?}`, `stop-looking {}`.
- `GET listings?floor=F7|M7`, `GET listings/{id}`. Listing ETags include process epoch.
  Listings include `leader_uuid` for opening the leader's player card.
- `GET player-card/{uuid}`: same payload as `auth/player-card`, for a member of
  a visible listing or the viewer's own party (including paused/full parties).
  Requires sign-in; hidden/blocked parties and accounts outside a party return 404.
  Reuses the bounded player-card cache; no credentials or block lists are returned.
- `POST reserve {party_id, role}`, `leave {}`.
- `POST publish {version, floor, leader_class, roles, allow_duplicates, rules,
block_names}`, `edit {rules, blocked, block_names}`, `pause {paused}`, `unlist {}`,
  `remove {member, block}`. Only the leader may manage a party. Authentication and
  leader checks precede external name lookups. Blocks persist by UUID within the listing.

Each player has at most one search/held slot. Matching uses F7/M7 separately and
the stricter shared/class-specific requirements; absent required values fail.
Manual reservations allow any qualifying open class, independently of the classes
selected for automatic matching. Fresh browsing and creation default to M7;
an existing search or held party retains its actual floor.
Full parties are delisted, **not deleted**. Once full, offline players have five
minutes to connect to Hypixel; no-shows lose their slot and receive the existing
one-hour finder cooldown. Once an invite round is claimed, that offline deadline
ends; failing to accept is not itself a no-show penalty. Before filling, closing
both site and mod releases a slot after 60 seconds. After invitations, the same
absence grace applies without the no-show penalty. A departing leader is replaced
only by a member whose website or mod is currently present; otherwise the party closes.

### Mod handoff

- `POST party/mod/presence {version, online}`: online means connected to Hypixel,
  not a title screen/private server. Returns `{version, interval_seconds, party}`.
  Party is null or a compact view with `party_id`, `handoff_id`, `leader`, `you_lead`,
  `full`, `invited`, and members `{name, online, accepted}`. No arbitrary commands.
  Presence only tracks accounts already using the finder.
- `POST party/mod/roster {version, party_id, handoff_id, leader, members}`: current
  leader reports a complete `/party list` response. Names must be a subset of the
  expected roster, with the expected game leader. Extra members/different leaders
  block handoff; the mod never kicks/disbands/leaves to fix that automatically.
- `POST party/mod/invite` uses the same body plus `retry`. With `retry:false`, an
  atomic claim permits one automatic round only, after all five are currently online.
  The reply's `invite` list contains only missing usernames. Repeated claims return
  an empty list. Uncertain responses do not trigger an automatic repeat. With
  `retry:true`, the leader explicitly retries missing players (10-second cooldown).
  The mod command is `/mithrilpfreinvite`; commands are paced one per second.
- `handoff_id` changes when the roster changes. Stale claims/reports are rejected.
  A full exact game roster closes the listing and emits `party_joined`. Game
  presence alone cannot do this. Partial acceptance remains visible to the website.
  Before completion, a departure reopens the same party ID. After completion,
  players create another listing if needed; there is no automatic recreation.

The mod requires English Hypixel party-list messages; incomplete/unknown/expired
responses fail closed. It checks game membership every ten seconds during handoff.
Actual server timing, message formatting, chat visibility and multi-client behavior
still require Minecraft testing. A scope is not anti-cheat: observed roster reports
are authenticated client input, not cryptographic proof of Hypixel membership.

## Operations and limits

Use one backend process: parties/searches/cooldowns/notices are in memory, bounded
at 4000 players/800 parties, and do not survive restarts. Auth and PBs use locked
SQLite stores. Mod presence has a 60-second freshness window. HTTP requests are
bounded at 4 KiB; mod responses at 16 KiB. Reverse-proxy limits and rollback are in
DEPLOYMENT.md. Restart recovery does not silently restore a closed finder party.

Run `python tools/check.py`; fixtures/fakes never contact accounts or production.
Before deploying: test full five-client handoff, no-shows, manual reinvites, a roster
change during an invite round, unrelated existing game parties, browser logout,
account switch, network loss and backend restart. Automated tests do not replace this.
