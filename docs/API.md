# API v1

## Run link previews

`GET /runs/{record_id}` serves the built application with server-rendered Open
Graph metadata: floor, PB time, player and an optional map image. `GET
/api/v1/records/solo/{record_id}/preview.png` generates a 1200×630 PNG from the
retained 300-score snapshot in memory. Both support HEAD, need no login, and
reuse the public solo-record eligibility rules. Missing, erased or hidden records
return 404; retired/missing maps omit the image metadata and return 404 from the
image route. There is no additional image storage or server cache. Other sites
can cache a preview after fetching it.

## Optional Discord foundation API

`GET /internal/v1/leaderboards` returns the synthetic shape in
`contracts/discord-leaderboards-v1.json`: `version:1`, `updated_at` and three boards
(`f7_solo`, `m7_solo`, `m7_terminals`). Each row contains UUID, nullable last
authenticated Minecraft name, rank, real_ms and ticks from one eligible observation.
Each player contributes their best record per category. Solo ranks use ticks only
and UUID for deterministic ties, returning ten players. M7 terminals sort by real_ms
then ticks and use ten dense ranks, including all players tied at rank ten.
F7 terminal records never participate. Existing eligible legacy, manual and
single-report records remain eligible; active account/network bans and invalidated
records are excluded. No new client submission or Discord link is required.

Record names are retained alongside PB summaries, captured from accepted mod
submissions and backfilled from authenticated sessions (never pending proof names).
They are erased atomically with PB/account deletion.
Unknown names remain null and are displayed as UUIDs. This introduces the additive
`record_names` table. The bot refreshes once per minute and removes stale content
on backend failure. Record deletion/moderation affects the next successful refresh;
Discord access failures may delay this. The endpoint remains authenticated,
loopback-only and no-store. Each board is bounded at 1,000 players; overflow returns
503 rather than truncating a tie group. No gameplay evidence or credentials are exposed.

The Discord bot uses a separate authenticated loopback listener on `127.0.0.1:8781`,
never the public API or nginx. `GET /internal/v1/summary` returns service time,
aggregate open-party/search counts for F7/M7, the latest known mod version and
recent Finder profile lookup health. Names, UUIDs, reports and credentials are absent.
Health is `unknown` with no observed fetch in five minutes, `failing` when the last
fetch failed, `slow` if recent successful service includes failures or >=2-second
fetches, otherwise `ok`. This measures Finder lookups, not every Hypixel endpoint.

`GET /internal/v1/releases` reuses the existing five-minute ReleaseCache fetch and
returns up to ten supported published releases ordered by version, with official
JAR/page links, GitHub-provided SHA-256 asset digests and notes capped at 3,000
characters. Drafts and missing digests are excluded from announcements. Cache status
is `ready`, `stale` or `unavailable`; the bot announces ready data only. Public
`mod-release` behavior and response shape remain unchanged. No detached JAR signature
is claimed. Synthetic examples are in `contracts/discord-foundation-v1.json` and the
Discord repository; compare their hashes for coordinated protocol changes.

The internal listener checks the actual loopback peer plus a constant-time comparison
of its separate bearer secret. It rejects bodies and mutations, does not trust proxy
headers, and serves no public/account routes. The public listener serves no internal
routes even with valid internal authorization or forged forwarding headers. Both
listeners share one process/event loop, keeping Finder state authoritative. Phase 1
creates no identity links, event feed, new user data or Discord moderation mutations.

All production requests use `https://mithril.foo/api/v1`. Responses and explicitly
versioned request bodies use `version: 1`. Synthetic fixtures live in `contracts/`;
Python and frontend tests check their meanings. No real accounts belong in fixtures.

## Mod download

`GET mod-release` is public and returns `{status, release}`. Status is `ready`,
`none` (no supported published release), or `unavailable`. A ready release contains
`{version, url}` pointing directly to the versioned JAR on GitHub. Metadata uses
the highest supported version among GitHub's ten recent releases, cached for five
minutes. Published alpha/beta/rc builds are included and labelled Beta in the UI;
drafts and releases without the expected gameplay JAR are excluded. Stable wins
over prereleases of the same version. Failed refreshes retain a known good link
and retry after one minute.
No GitHub credentials or proxying of JAR contents are involved.

## Slayer prices

`GET slayer-prices` is public, sets no cookie, and returns
`{version:1, bazaar, npc, auctions, pets, feeds}` for `/slayer-profits`.
`bazaar` maps item IDs to `{instant, offer}`; `npc` maps item IDs/names to sell values.
`auctions` maps drop names to `{price, source, samples, spread}`; source is `BIN`,
`Recent sales`, or `Unstable BIN`. `pets` contains profitable Combat pet pairs with
`{name, rarity, endRarity, startLevel, endLevel, startPrice, endPrice, requiredXp,
samples, historyHours, kat}`. `historyHours` counts observed hourly price buckets
(up to 168); fewer than 168 means provisional. `kat` is null for same-rarity
leveling or `{coins, materials, flowers, flowerCost, total}` for a Common to
Legendary route. All costs except `flowers` (a count) are coins. Pet profit
subtracts `kat.total` as well as the purchase price before dividing by XP.
`feeds` contains `bazaar`, `npc`, `auctions`, and `sales`, each with
`{status, updated}` (epoch seconds or null). Status is `loading`, `ready`, `stale`,
or `unavailable`. Missing prices are omitted rather than invented. The calculator
ships its factual drop catalogue and performs expected-value calculations locally.

The server fetches only fixed, public Hypixel endpoints without an API key or
player lookup. One background loop continuously collects Bazaar and pet prices;
NPC and recent-drop sales refresh while the page has been used within 15 minutes.
Bazaar refreshes every five minutes, NPC data hourly, Auction
House every 15 minutes, and recently ended auctions every minute. Requests return
the current snapshot immediately. Failed feeds back off for one minute, retaining
last-known values for at most 24 hours. Browser refresh does not bypass these limits.
An auction scan uses at most four concurrent requests, 200 pages, and a 90-second
budget checked between batches. All pages must share the same snapshot timestamp.
Responses and decompressed JSON are limited to 16 MiB; item NBT to 2 MiB with
depth/element bounds. Network operations run off the application event loop.

Recent sale history is process-local, deduplicated, and limited to 20 samples per
eligible item over 24 hours; it resets on restart. No player or auction identifiers
are returned to the browser. The endpoint uses the existing public nginx rate limit.

Pet history persists in `pet-prices.sqlite3` beside the auth database. It stores
one aggregate price per pet name/rarity/level/hour for seven days, never raw
listings or player/auction IDs. Endpoints require three low listings within 25%.
Skins and Tier Boost pets are excluded. The baseline is the mean of prior hourly
observations within [median / 1.5, median * 1.5]. After 24 prior observations, a
current price outside [baseline / 1.5, baseline * 1.5] is excluded. Outliers are
retained in history so sustained market changes can establish a new baseline.
Buy prices use max(current, baseline), sale prices min(current, baseline).
Estimates are available immediately and labelled provisional while history builds.
This is an asking-price heuristic, not a guarantee of sale liquidity.

Common resale pairs are excluded. Common to Legendary routes require a complete
Kat recipe, a Legendary level-100 resale quote, and all ingredient/flower prices.
They require 25,353,230 XP and subtract all four upgrades: 30% level-100 coin
discount, undiscounted materials at Bazaar instant-buy prices, and
sum(ceil(each upgrade's seconds / 86400)) Kat Flowers. Missing prices exclude the
route. Flowers use Bazaar instant-buy or current AH asks. No unpriced material is
assumed free. Only Combat pets are considered, matching the existing XP model.

## Account linking and scoped mod credentials

The user starts linking in Minecraft. `POST auth/challenge` accepts `{version,
uuid, name, client_nonce}`: UUID is 32 lowercase hexadecimal characters; name is
1–16 ASCII letters, digits or underscores. Each attempt uses a new cryptographically
random 32-byte `client_nonce`, encoded as 64 lowercase hexadecimal characters.
The backend returns a fresh 64-hex `server_nonce`, a 43-character URL-safe
`challenge_id`, 39-hex `server_id` and 60-second lifetime. `server_id` is the first
39 lowercase hexadecimal characters of SHA-256 over the UTF-8 string
`mithrilpf:ownership:v2:<scope>:<uuid>:<client_nonce>:<server_nonce>`, where scope is
`link`, `sync` or `party`. The mod independently computes this value and rejects
a missing nonce or mismatched hash before contacting Mojang. It never falls back
to a server-chosen hash. Binding both nonces prevents a malicious backend from
substituting a Minecraft server login hash while preserving backend freshness.
For compatibility the backend still accepts omitted `client_nonce` from old mods;
those clients need an update to gain this protection. Deploy the backend before
the updated mod, which intentionally rejects old backends.

Minecraft proves ownership
through Mojang's `joinServer`. **Only Mojang receives the Minecraft access token.**
`POST auth/verify` consumes `{challenge_id}` once and checks Mojang `hasJoined`.
The reply contains `link_token`, `receipt_token`, `user_code` (`ABCD-EFGH` format)
and a 300-second lifetime. Existing long-token clients remain supported.

Anonymous challenge creation is limited to 10 requests/client/minute and 300
globally/minute; anonymous verification has a separate 20/client/minute and
300/global/minute budget. Limits use sliding 60-second windows and return 429
with `Retry-After` seconds. Rejections do not extend the window, create tokens,
consume proofs or call Mojang. Admitted failed verification attempts count too.
Clients are identified by the trusted ASGI peer address, not claimed Minecraft
identity or raw forwarding headers. IPv6 addresses share a /64 budget; IPv4-mapped
IPv6 shares the corresponding IPv4 budget. Addresses are held in bounded process
memory (expired entries are evicted on the next request), never persisted or
logged by the limiter. Users behind the same public IP share the allowance.

At most two anonymous and two linked-credential ownership lookups run concurrently.
Linked verification requires a valid receipt before using its reserved capacity
and rechecks the receipt after the lookup. Capacity rejection returns 503 with
`Retry-After: 1` without consuming the challenge; an actual verification attempt
still consumes it once. Existing party/record operations do not use the anonymous
budgets. These safeguards bound work, not guarantee access during a distributed
attack; global-budget exhaustion can temporarily deny new links. Limits reset on
process restart; the store's row caps remain a final bound.

Pending challenges (each kind), browser links and unconfirmed receipts each have
a 1,000-entry cap. Confirmed receipts use a separate 100,000-entry cap, as do
sessions, sync credentials and party credentials (each kind). Established links
therefore do not consume the pending-link allowance. These are storage bounds,
not a guarantee of concurrent-user capacity. Expired entries are reclaimed on
issuance; startup/hourly cleanup also removes established credentials with no
valid parent session. Logout/replacement removes that session's credentials immediately.

Link, receipt and short-code issuance is one transaction: a capacity or write
failure leaves none of the new records behind. The ownership challenge remains
single-use, so retry verification failures with a fresh challenge. Browser
completion/resume also runs as one transaction, including link redemption,
session replacement/renewal and receipt confirmation. Failure preserves the
unexpired link/code and the previous session for retry. No existing valid
sessions or receipts are evicted to admit another user; full capacity returns 503.
Sync tokens keep their existing 15-minute lifetime and are not invalidated by
another sync authorization; party-token replacement behavior is unchanged.

The mod opens `https://mithril.foo/link#<link_token>`. The browser removes the
fragment, previews the account with `POST auth/preview {token}`, and explicitly
confirms it with `POST auth/complete {token, remember}`. Confirmation consumes the
link and replaces this browser's previous session.
`preview` adds `already_linked: true` only for a valid browser session with the same
UUID. In that case `POST auth/resume {token}` consumes the link, confirms its mod
receipt against the existing session, and renews that session/cookie without
changing its remember-browser choice or revoking existing mod credentials. The
browser then replaces the link page with `/party-finder`. Missing, expired or
different-account sessions still require explicit confirmation; resume rejects
them without consuming the link. `GET auth/session` returns
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

| Scope   | Challenge / verification                    | Credential    | Lifetime   | Permitted use |
| ------- | ------------------------------------------- | ------------- | ---------- | ------------- |
| Records | `auth/sync-challenge`, `auth/sync-verify`   | `sync_token`  | 15 minutes | `records/*`   |
| Parties | `auth/party-challenge`, `auth/party-verify` | `party_token` | 30 days    | `party/mod/*` |

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
one another's Mojang server proof.

## Native Minecraft sessions

The in-game finder uses an independent session; closing or logging out of a browser
does not revoke it. `POST auth/device-challenge` requires `{version: 1, uuid, name,
client_nonce}` and returns the same challenge fields as browser linking. The proof
scope is `device`; the nonce is mandatory. `POST auth/device-verify {challenge_id}`
consumes that challenge and returns `{version: 1, user, device_token, receipt_token,
expires_in_seconds: 2592000}`. The usual anonymous proof budgets and concurrency
limits apply. Issuance checks account erasure generations and atomically saves the
session and receipt. At most ten unexpired Minecraft sessions per account are allowed.

Native requests use `Authorization: Bearer <device_token>` and reject Origin headers.
Browser cookies, presence credentials and upload credentials cannot authorize them.
The native session cannot authenticate a browser. Tokens are stored hashed on the
server; the mod saves its credential and receipt per account in instance-local
`config/mithrilpf/device.json`. Sessions expire after 30 days without sliding renewal.

- `GET auth/device-session`: `{version: 1, user, expires}` or 401.
- `POST auth/device-logout`: revoke this session and its receipts/scoped credentials.
- `GET auth/device-player-card`: the account-card response using native authentication.
- `POST auth/device-erase`: the same explicit erasure body and rules as `auth/erase`.
  Restricted accounts retain access to erasure.
- Browser-authenticated `GET auth/devices`: `{version: 1, devices: [{id, name, expires}]}`.
  IDs are hashes, not usable credentials. Origin-protected `POST auth/devices/revoke
{id}` revokes only a Minecraft session belonging to that browser's account.

The receipt can obtain separately scoped party and record credentials through the
existing proof routes. Each scoped request checks its parent session, whether browser
or native. Account deletion removes both kinds and rejects ownership proofs already
in flight. Browser logout continues to revoke only that browser's children.

The native finder mirrors the browser finder under `party/client/`: `state`, `look`,
`stop-looking`, `reserve`, `leave`, `publish`, `edit`, `pause`, `unlist`, `remove`,
`chat`, `chat/report`, `listings` and `listings/{party_id}`. Methods, request bodies,
responses and matching rules are unchanged. Listings require authentication and hide
blocked players' parties. Bans, mutes and post-wait/post-lookup authentication checks
also apply to native requests. Native UI activity keeps the finder slot alive; only
the existing `party/mod/presence` heartbeat reports actual Hypixel presence.

## Account card and records

`GET auth/player-card` derives the UUID from the browser session. It returns selected
Hypixel profile data (not merged profiles): Catacombs XP/level, secrets, highest recorded
magical power, and S+ PBs for F1–F7/M1–M7. Missing values are null. Account-wide mod
records are shown separately; SS is not collected yet. See `player-card-v1.json`.
Catacombs and all five dungeon class levels include fractional overflow above 50
at 200,000,000 XP per level.

`POST auth/sync-records` now returns 410 after authentication. Existing bests migrate
once into individual legacy entries and remain eligible until moderated. Old clients
cannot introduce new untracked improvements. Real-time and tick bests remain independent.

New submissions use the scoped sync token and `version: 2` bodies:

- `POST records/solo-start {version, floor, elapsed_ms, ticks, paul}` registers a
  fresh F7/M7 attempt, at most ten seconds after Mort's start. The response includes
  a random `attempt_id`, `nonce`, `sequence: 0`, and `status: active`.
- `POST records/solo-progress {version, attempt_id, nonce, sequence, elapsed_ms,
ticks, roster, dead, valid, evidence, complete}` acknowledges the last nonce and
  increments sequence by one. `roster` contains observed player UUIDs, cumulatively;
  only the submitting player is permitted. `evidence` supplies the bounded score
  inputs in `contracts/solo-score-v2.json`. The backend recomputes the projected
  score, including Paul, unfinished blood/boss and speed penalties. It must observe
  a score below 300 before a qualifying finish at 300 or above.
- `POST records/terminal-report {version, report_id, floor, run_started_ms, roster,
real_ms, ticks}` accepts a single report as eligible. Reports by different accounts
  with the same floor, roster and start within ten seconds are compared. A spread
  greater than one second or twenty ticks is flagged for review; matching reports
  become corroborated. A conflicting witness cannot automatically erase another
  player's record. Per-account run reports are unique; identical retries are idempotent.

Live samples are sent every five seconds, with an immediate finish sample. Each
acknowledgement supplies an unpredictable nonce for the next update. An exact retry of
the last accepted progress request within fifteen seconds returns its original reply,
without extending the evidence window or writing another record/map. A digest binds
all request fields, including the previous nonce and optional map; only the digest
is retained alongside the existing evidence. Changed requests, older replays, reordered
updates, non-solo rosters, deaths, invalidated tracking, gaps over fifteen seconds,
client/server elapsed disagreement over five seconds, and implausible tick rates
reject the attempt permanently. At least three progress messages are required.
Tick counts must fall between elapsed/250 and elapsed/50 + 40. These conservative
bounds reject extreme clock discrepancies, including genuine extreme lag; local
PBs are still retained. No record is labelled proof of legitimate gameplay.

The client uses bounded queues and a background worker; it never submits stored
local minima as fresh evidence. Offline attempts remain local. Queued starts older
than ten seconds and progress older than five seconds cannot qualify. The server
bounds active attempts at 1,000, each account at 500 starts/reports per day, each
attempt at 1,500 updates, and a run at two hours. Terminal start timestamps must be
within the past day. Client-reported run identity and timings remain forgeable.

Accepted attempt details and terminal report context expire after thirty days;
rejected/abandoned attempts expire after seven. Eligible record summaries persist
until deleted. Case-specific holds can extend evidence retention or suspend expiry
for an open appeal. Cleanup runs hourly in a worker. A restart abandons active
attempts. Accepted records refresh the party matching cache on the event loop.
Browser logout revokes submission credentials but does not delete records.

`GET auth/skin` serves a validated Mojang skin for the signed-in UUID; arbitrary
URLs/redirects are rejected. The lazy skin renderer's licenses ship in
`/skin-viewer-licenses.txt`. No analytics or third-party browser skin requests.
`GET party/skin/{uuid}` uses the same bounded skin cache, requires browser sign-in,
and accepts only the viewer, members of their current party, or senders in its
retained chat history. Avatars crop the face and hat layers from this texture;
the account avatar and 3D preview share the same browser-side request.

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
  `full`, `invited`, and members `{name, uuid, online, accepted}`. `uuid` is the
  undashed Minecraft UUID, so the mod can match Hypixel Mod API party info; older
  mods ignore it. No arbitrary commands.
  Presence only tracks accounts already using the finder.
  Presence, roster and invite replies also include optional `activity`: null when
  idle, or `{floor, leader, members}` for the authenticated player's own Discord
  Rich Presence. A search has `leader:null, members:0`; a held/private party has
  its leader's username and member count (1–5), including after handoff. No party
  ID, join secret, requirements or credentials are shared with Discord. Existing
  clients can ignore this additive field.
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
  A full exact game roster makes the session private and emits `party_joined`. Game
  presence alone cannot do this. Partial acceptance remains visible to the website.
  Before completion, a departure reopens the same party ID. After completion,
  players leave the private session and create another listing if needed; there
  is no automatic recreation. The private chat remains available during the run.

The mod requires English Hypixel party-list messages; incomplete/unknown/expired
responses fail closed. It checks game membership every ten seconds during handoff.
Actual server timing, message formatting, chat visibility and multi-client behavior
still require Minecraft testing. A scope is not anti-cheat: observed roster reports
are authenticated client input, not cryptographic proof of Hypixel membership.

### Party chat

`POST party/chat` uses the browser session and same-origin checks, with
`{version:1,party_id,request_id,text}`. It returns the updated personal party state.
The existing held `party/state` request wakes immediately for party messages; there
is no separate browser connection or short-interval polling. Session validity is
checked again after a held request. A party's `messages` field contains the latest
100 messages, including on refresh/reconnect. It is never in public listing/detail
responses. Each message is `{id,text,at,sender:{uuid,name},source}`; `at` is epoch
milliseconds and `source` is `web` or `game`. IDs are increasing decimal strings
within one party. The server derives the sender from authentication, never input.

Text is 1–256 Unicode characters, trimmed, plain text; controls, directional
overrides and Minecraft formatting codes are rejected. `request_id` is a client
generated 16–64 character URL-safe identifier; reuse it when retrying the same
send. Retries are deduplicated for ten minutes (bounded to 1024 receipts per party);
changed text/source with the same ID is rejected. Sending is limited per account
to five messages in five seconds and twenty per minute (HTTP 429). Readers and
writers must still belong to the exact party; removal/leave immediately revokes
access, including on held mod reads. New members can read retained party history.

The mod transport is available under the existing scoped party credential:

- `POST party/mod/chat/send` accepts the same payload and returns
  `{version:1,message}`.
- `POST party/mod/chat/state` accepts `{version:1,party_id,after:0}`. It holds for
  up to 25 seconds if caught up, then returns `{version:1,party_id,latest,messages}`
  containing retained messages after that sequence. A reader falling behind more
  than 100 messages receives only retained history. Membership and credentials are
  rechecked after waiting. This read does not replace the presence heartbeat.
- `party/mod/presence` additionally returns `chat_party_id` (nullable), including
  after handoff. Old clients can ignore this additive field. The mod chat
  reader bounds responses at 256 KiB, separate from the 16 KiB handoff limit.

After handoff, `party.completed` is true and the legacy mod handoff `party` is
null so old clients stop inviting. The private session never relists automatically,
even when members leave. The existing 60-second absence policy still releases
members with neither the site nor mod connected; no no-show penalty applies.

Website members and mod clients using `/mpc` exchange messages in the same party.
Nothing is forwarded to Hypixel chat or interpreted as commands. History lives
only in process memory: leaving/expiry of the last member, disbanding or a backend
restart deletes it. It is not logged or
saved in the account/record databases. No additional cookies are used.

## Operations and limits

Release metadata for the Discord bot may include an optional `checks` object:
`tests` (passing JVM tests), `line_coverage` and `branch_coverage` (percent), and
`run_url` (the official release workflow). It comes from a bounded hidden release
notes comment generated by that workflow and matched to the version and JAR
SHA-256. The comment is removed from displayed notes. Missing or malformed metrics
are omitted without suppressing the release. No additional network calls are made.

### Solo-clear map snapshots

Version 2 `POST /api/v1/records/solo-progress` accepts an optional `map` on a
completion report only. Capture freezes at the same 300-score observation as the
PB. Existing clients can omit it. This route allows a 640 KiB request; all other
request body limits remain 4 KiB. Map metadata is bounded to 16 KiB of UTF-8 JSON;
the complete map including replay is bounded to 620 KiB when read from storage.

The v1 map contains `version:1`, `rooms` (1–36), and `doors` (0–60). Room `tiles`
are unique, connected indices on a 6×6 grid (row-major 0–35, up to four per room).
Each room includes optional `name` (64 characters maximum), `type`, `state`,
`secrets_found` and `secrets_total` (0–100 or null on capture failure). Room types
are UNKNOWN, NORMAL, RARE, ENTRANCE, BLOOD, FAIRY, CHAMPION, PUZZLE or TRAP;
states are UNKNOWN, UNOPENED, DISCOVERED, CLEARED, COMPLETE or FAILED. Doors
join adjacent tiles in distinct rooms with ordered `a < b` and type UNKNOWN,
NORMAL, WITHER, BLOOD or ENTRANCE. Overlaps, duplicate doors and excess fields
are rejected. No pixels or individual secret locations are sent.

Map `version:2` adds required `elapsed_ms` and `ticks` to every room and a required
`stats` object containing `elapsed_ms`, `ticks`, `transit_ms`, `transit_ticks`,
`secrets_found`, `secrets_total`, and `crypts`. Times are nonnegative integers,
bounded to two hours (7,200,000 ms / 144,000 ticks). Room times include repeat
visits; each clock's room sum plus transit must equal its run total exactly.
Run totals must match the completion report and crypts must match its evidence.
Secret counts are 0–3600 or null, crypts 0–100 or null; null means not captured,
not zero. Known found counts cannot exceed known totals. All observations freeze
at the PB's 300-score cutoff. The page displays tick times to match the PB, plus
dungeon totals. Existing v1 maps remain readable without fabricating these fields.
`contracts/run-map-v2.json` is shared with the mod's snapshot regression test.

A v2 map can also contain `replay:{version:1,samples:<base64>}`. Decoded samples
are little-endian 12-byte records: elapsed milliseconds (uint32), world X and Z
in sixteenths of a block (int16 each), yaw (uint8, 256 steps per rotation), flags
(uint8), and cumulative observed dungeon secrets (uint16, 0–3600). Flag bit 0
breaks interpolation from the preceding point (teleport, large displacement or
capture gap); bit 1 means position unavailable, with coordinates zero and bit 0
also set. Mapped coordinates are bounded to the dungeon grid. The first sample
is at zero with bit 0 set; timestamps strictly increase and finish exactly at
`stats.elapsed_ms`. Interior samples are at least 200 ms apart; the final sample
can be sooner. At most 36,002 samples are accepted. Secret counts cannot decrease.
Bits 2–4 carry teleport kind: 0 none, 1 etherwarp, 2 instant transmission,
3 wither impact, 4 other/mixed; 5–7 are reserved. For a nonzero kind, bits 5–6
store count minus one, saturated at 3 (four or more). A mixed-kind chain is
other/mixed, never attributed entirely to its last ability. A nonzero kind requires
a mapped noninitial sample with bit 0 set. Count bits without a kind are invalid.
Bit 7 is a capability marker allowed only on the first sample; new writers set it
even for runs with no teleports. This keeps zero-event recordings distinct from
legacy recordings without adding bytes or changing replay version 1.

The browser infers legacy teleports only when neither the capability marker nor
any explicit kind is present: mapped endpoints, a break, at most 400 ms between
samples, and 3–60 blocks of horizontal displacement. Inferred counts say "about";
saturated counts say "+". Counts are attributed to landing rooms, including short
passes. New mod labels match a main-hand ability use less than 500 ms before the
packet and consume that hint once. Endpoints are sampled, not exact teleport
locations. Small displacements below 1.5 blocks, unmapped samples and gaps over
one second do not acquire teleport kinds. Unlabelled eight-block sample jumps
are other/mixed. Same-millisecond endpoint replacement preserves an existing
teleport kind unless the replacement has its own or becomes unmapped.
`contracts/run-replay-teleports-v1.json` is shared across all three implementations.
Deploy the accepting backend before distributing a mod that writes these flags.

`contracts/run-replay-v1.json` checks the mod encoder, backend and browser decoder.
Encoding happens on the mod's sync worker; database compression covers the entire
snapshot. Replay uses real elapsed time over the final map; it does not reconstruct
room states over time. Secret increases indicate when the global counter update
was observed, which may lag or combine pickups. Retention and erasure are shared
with the map, with no additional copy in progress evidence.

New replays optionally include `room_secrets`, a base64 stream of little-endian
six-byte events: elapsed milliseconds (uint32), the room's first tile (uint8),
and its observed collected count (uint8). Events are ordered by time through the
300-score cutoff and strictly increase per room, from an initial zero. Each must
refer to a room in the saved map and cannot exceed its known final or total count.
There are at most 3,600 events (28,800 base64 characters). Empty means recorded
with no increases; omission means the older client did not record this timeline.
Multi-tile observations collapse to one room; repeat visits do not double-count.
`contracts/run-replay-room-secrets-v1.json` is shared with the mod and frontend.
The browser seeks these counters independently of position samples, updating map
labels, selected-room details and the room list. For old replays without this stream,
the browser estimates room progress by assigning each global counter increase to
the room at that sample's position, capped at its saved final count. Unmapped
increases are not assigned or carried into later rooms; repeat visits accumulate.
These estimates are labelled as approximate and may miss delayed updates. The
final snapshot always uses the saved room counts. An empty recorded stream remains
authoritative and never triggers estimation. Observation
times may lag or group actual pickups; final room states and dungeon totals stay
labelled as the 300-score snapshot. The optional stream shares map retention and
erasure, with no additional table or copy. The 640 KiB upload allowance is unchanged.

`GET /api/v1/records/solo/{record_id}` is public and returns
`{version:1,record:{id,uuid,name,floor,real_ms,ticks,created},map}` for an eligible
solo record. Missing/ineligible/banned records return 404. `/runs/{record_id}`
renders these observations as SVG. Maps are client observations, not attestations.
The Discord leaderboard's solo rows optionally include `map_id` for a retained
map; it is the record's 43-character ID, never an arbitrary URL.

Only the current best by ticks, then creation time and ID, keeps a map per UUID
and floor. Faster PBs, including submissions without a map, discard the previous
map. Slower/equal submissions are not retained. Invalidation/correction prunes maps;
restoring a record does not restore discarded data. Erasure removes maps too.
Old eligible run links return `map:null`. Snapshots are compressed separately in
`pb_maps`, never duplicated into the expiring live-attempt evidence.

Use one backend process: parties/searches/cooldowns/notices are in memory, bounded
at 4000 players/800 parties, and do not survive restarts. Auth and PBs use locked
SQLite stores. Mod presence has a 60-second freshness window. HTTP requests are
bounded at 4 KiB (640 KiB for solo-progress); mod handoff responses at 16 KiB and
chat responses at 256 KiB.
Reverse-proxy limits and rollback are in DEPLOYMENT.md. Restart recovery does not
silently restore a closed finder party.

Run `python tools/check.py`; fixtures/fakes never contact accounts or production.
Before deploying: test full five-client handoff, no-shows, manual reinvites, a roster
change during an invite round, unrelated existing game parties, browser logout,
account switch, network loss and backend restart. Automated tests do not replace this.

## Moderation and privacy

All `/api/v1/moderation/` requests require a linked browser session and an active
moderator grant, or the configured owner UUID. Mutations require the exact web
Origin and a v1 JSON body with a nonblank reason (500 characters maximum).
Owner-only `POST access` grants/revokes a UUID; grants survive renames and restarts.
`GET access`, `GET player/{uuid}`, `GET resolve/{name}`, and paginated `GET audit`
provide access, records/cases, current Mojang names and attributable history.
No panel endpoint returns credentials, raw IPs or keyed connection identifiers.

`POST record` accepts a record_id, expected_status and invalidate/restore/correct.
Corrections require real_ms and ticks; they invalidate the reviewed record and
create a manual replacement. Changes and before/after audit values commit together.
Old or duplicate edits fail with 409. Finder PB fields refresh without requiring a
Hypixel request. Historical legitimate records can still supply the player's best.
`GET evidence/{record_id}` and `GET case/{case_id}/evidence` show retained evidence;
case evidence remains accessible after a player deletes their PB summary.

`POST sanction` accepts uuid, kind (ban/network_ban/mute), optional Unix expires
(null means permanent), record_ids and report_ids. Network bans also restrict the
account and use its latest authenticated mod connection from the past 24 hours.
They match exact IPs (IPv4-mapped IPv6 is normalized), can affect shared networks,
and do not prevent VPN or account evasion. Account bans remove current party/search
state and apply to browser, mod and record routes. Mutes block both chat send routes.
Account management remains accessible while banned. No discrepancy automatically bans.
`POST case` revokes a sanction or opens/closes an externally handled appeal.

`POST /api/v1/party/chat/report` requires current party membership and references a
server-side message_id; clients cannot submit evidence text or a sender identity.
Reports are limited to ten per account per day, 10,000 retained globally, and duplicate
reports from the same account are idempotent. Ordinary chat remains in memory.
Moderators use GET/POST moderation/chat to inspect, dismiss or remove reported messages.
Removed text is scrubbed from retained chat and retry receipts; mod history omits it.
Previously rendered Minecraft chat cannot be recalled. Report text expires after
30 days unless a case hold applies; audit entries do not copy the message text.

### Curator review

Owner-only routes manage the daily item answers for Curator. They need the owner's
browser session; POSTs need the exact web Origin and a v1 JSON body but no reason.
`GET curator` returns the sales cut-off, the first day with collected auction sales,
item counts per status, the number of items added since the last review and the
answer queue for today and the next 29 UTC days. Missing days are picked on read,
weighted towards items with fewer auction sales and avoiding earlier answers.
`GET curator/items?group=&query=&offset=` pages 50 items at a time; groups are pool,
admin, new, allowed, blocked and all.

`POST curator/list` takes item and list (allow, block or null). Allowed items skip the
cosmetic and popularity filters; blocked items never become answers. Items whose name
or clues match another guessable item stay out of the pool either way.
`POST curator/day` takes a day and an item ID, or null to pick another item; only
coming days in the queue can change. `POST curator/settings` sets sales_cutoff, the
30-day auction sales above which an item is too popular, and `POST curator/reviewed`
marks every current item as reviewed.

Evidence holds follow temporary restriction expiry, or 30 days after a permanent
restriction. An open appeal holds evidence until it closes, then the original
expiry applies. Late appeals cannot recover deleted detail. Unrestricted accepted
run evidence expires after 30 days and rejected/abandoned evidence after seven.
Minimal audit history expires 180 days after the account's last case ends; active
restrictions and open appeals defer that expiry. Standalone actions expire after
180 days. Cleanup runs hourly. Recent keyed connection associations expire after
24 hours, and expired/revoked network restrictions drop their connection fingerprint.

`POST /api/v1/auth/erase` takes version:1, scope:records|account and
confirmation:"DELETE". It requires the browser session and exact Origin. PB deletion
removes synced summaries and unheld evidence, revokes sync credentials and clears
cached requirements. Account deletion also removes authentication links, moderator
grants, recent connections, ordinary chat and player caches. Restrictions, open
reported-message investigations and required evidence/audit records retain the
limited lifetimes above. Local Minecraft files are not changed or uploaded again.
New deliberately recorded runs can create new PBs after reauthentication.

Auth and record deletion commit in one attached SQLite transaction, under the
records-then-auth lock order. Record writes reauthenticate under that same lock.
Ownership-proof issuance checks an erasure generation so a proof already in flight
cannot recreate a deleted link. Pending skin/stat fetches cannot repopulate erased
caches. A separate seven-day erasure ledger is replayed before serving restored
records; see DEPLOYMENT.md. GET /api/v1/privacy publishes the operator/contact from
server configuration. `/account` provides self-service deletion and `/privacy`
explains purposes, retention, exceptions and contact rights.
