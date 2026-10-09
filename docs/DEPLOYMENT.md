# Deployment

## Solo-clear maps

Teleport-aware replay clients set a first-sample capability bit and pack teleport
kinds/counts into the existing flags byte. Deploy the matching validator and
frontend before publishing such a mod build; earlier validators reject flags above 3. No schema migration, new payload bytes or extra samples are needed. Keep the
accepting validator deployed once these recordings exist. Legacy replay inference
works immediately, while new zero-event recordings explicitly disable inference.

Run link previews require the `/runs/` nginx proxy and the built
`frontend/dist/index.html` beside the backend. The backend injects Open Graph
metadata into that template; `/api/v1/records/solo/{id}/preview.png` renders a
1200×630 PNG with Pillow directly from the retained map. No generated images or
extra database rows are stored. Both routes reuse public-record eligibility and
return no-store responses. External chat services may retain their own previews.

Map capture adds the idempotent `pb_maps` table to records.sqlite3. Back up the
database and deploy the backend/frontend plus updated nginx configuration before
the mod and bot. Only `/api/v1/records/solo-progress` has a 640 KiB body allowance;
other requests retain 4 KiB. Validate nginx before reload. Verify a synthetic
map upload, current-best replacement, public page, ban/invalidation and erasure.
Do not seed production with synthetic player records.

Map v2 adds room timing, dungeon totals and an optional replay without a database
migration. Its replay raises the solo-progress body limit from 32 to 640 KiB;
deploy and validate the updated nginx configuration too. Deploy v1/v2 backend
and frontend support before releasing the v2
mod: an older backend rejects that map format. After v2 clients are distributed,
keep a compatible reader/validator deployed and recover with a forward fix.

The map-aware erasure path must remain deployed while maps exist. Recover with
a compatible forward fix; do not restore an older writer/deletion implementation
or stale database. Keep the independent current erasure ledger during recovery.
At most two compressed maps with optional replays are retained per player (one per floor). Deleted
SQLite pages are reused; file size need not shrink immediately. Normal seven-day
backup expiration and erasure replay also apply to these snapshots.

## Optional Discord listener

Leaderboard support adds an idempotent `record_names` table to records.sqlite3;
back it up with existing records. Deploy the updated backend before enabling the
bot's leaderboard channel. Verify ranked clocks, equal terminal groups and removal
after invalidation or erasure. The new privacy erasure path must remain deployed
while retained record names exist; use a compatible forward fix for backend recovery.

Deploy the matching tested/public source before enabling the Discord bot. Install
`deploy/discord-listener.conf` as a drop-in for `mithril-web.service`; the existing
unit remains the default for installations without Discord. Generate a separate
32-byte random lowercase hexadecimal secret in root-owned mode-0600
`/etc/mithril-discord/internal-secret.txt`. systemd LoadCredential supplies it to
both services without granting the bot access to web databases or the Hypixel key.

The drop-in runs `python -m mithril_web.serve`: public port 8780 and internal port
8781 both bind only `127.0.0.1`, within one Uvicorn process and one Finder event loop.
Only port 8780 trusts nginx forwarding headers. Never proxy 8781 through nginx or
add extra web workers. Test unauthenticated internal requests (401), public internal
paths (404), spoofed forwarding headers, unchanged public health/auth behavior and
aggregate status before starting the bot. The source-only extension adds no schema
migration. Disabling the bot does not affect matching; rollback of the bot is separate.

Production serves `https://mithril.foo`; www redirects to the root.
The .foo domain requires HTTPS. Serve the frontend and API from one origin,
with the backend bound to loopback behind nginx. Keep other hosted services unchanged.

## Release layout

- `/opt/mithril-web/releases/<release>/`: root-owned source, frontend build and venv.
- `/opt/mithril-web/current`: active release symlink.
- `deploy/mithril-web.service`: unprivileged mithril-web service, loopback port 8780.
- `/var/lib/mithril-web/`: persistent auth.sqlite3, records.sqlite3, pet-prices.sqlite3 and
  curator.sqlite3.
- `/etc/nginx/sites-available/mithril.foo`: installed deploy/nginx.conf.
- `/var/www/mithril-web-acme`: certificate challenge webroot.

The service reads `HYPIXEL_API_KEY` from a root-only environment file at
`/etc/mithril-web/hypixel.env`, loaded through its systemd drop-in. The file must
be mode 0600 inside a 0700 directory. Never print or package it. Preserve the file
and drop-in across releases. Development keys are temporary; production needs an
approved application key. API credentials never reach browsers or mods.

## Deploy and roll back

1. Publish the corresponding source for the version being deployed, including
   LICENSE, lockfiles and build/deployment instructions. Keep the shared footer's
   source link accurate (forks must update it). Do not deploy unpublished changes.
   Run all checks and build the frontend. Export production dependencies with
   `uv export --locked --no-dev --no-emit-project`.
   For a branch deployment, set `VITE_SOURCE_REVISION` to the published full
   commit SHA when running `npm run build` in `frontend`. This pins the footer's
   source and license links to the deployed revision without merging the branch.
2. Package backend source, built frontend, deployment files and
   tools/replay_erasures.py. Exclude
   local environments, Git, credentials, databases, node_modules and user records.
3. Create a new release and venv; install the export using pip `--require-hashes`.
   Verify backend imports as the service user without touching live user data.
4. Back up the persistent databases using SQLite's backup API and keep backups
   root-only. Preserve the previous release and any nginx configuration changed.
5. Switch the current symlink atomically, restart only mithril-web and verify
   HTTPS, health, authentication boundaries and served asset hashes.
6. Roll back by restoring the previous symlink and restarting the service.
   Keep persistent data in place; schema changes require a separate migration plan.

No CI job deploys. Never restore a stale database backup as a routine code rollback.
If nginx changes, run `nginx -t` before reload and check the existing hosts too.
Certificates cover root/www; renewal must validate and reload nginx. Use the
bootstrap config only for initial certificate issuance.

## Operational boundaries

Deploy the Slayer feature's `backend/mithril_web/slayer_data.json` with the Python
source and install the updated nginx config for `/api/v1/slayer-prices` and the
`/slayerprofits` to `/slayer-profits` redirect. After deployment, verify both routes,
the public price response, and eventual feed readiness. A cold Auction House scan
may take up to roughly two minutes; failure must leave a partial/stale indicator.
Pet-price history creates its own `pet-prices.sqlite3` beside the auth database;
include it in SQLite backups once present. Preserve it across releases and code
rollbacks. Existing auth/record schemas, credentials and dependencies are unchanged.
After deployment, verify that aggregate history is collected without page visits,
survives a service restart and returns provisional quotes while the week builds.

Curator data creates its own `curator.sqlite3` beside the auth database. It holds the
SkyBlock item catalog and daily auction sale counts per item ID, collected from the
keyless items list every six hours and the ended-auctions feed every minute; no player
data is stored. Include it in SQLite backups and preserve it across releases. After
deployment, verify that the catalog loads and that sale counts grow without page visits.

Curator rounds need the `/api/v1/games/` location from `deploy/nginx.conf`; install the
updated config and reload nginx with the release. Each UTC day starts with one full
Auction House and Bazaar scan for the market snapshot, which can take a couple of
minutes; until it finishes the mod shows the day as being prepared. Player results are
stored in records.sqlite3 (`curator_results`) and follow its backups and erasure.

API responses are not publicly cached. Authentication has an nginx limit of
30 requests/minute/IP (burst 15), party routes 60/minute/IP (burst 30).
Bodies are limited to 4 KiB. Held party state requests need a 40-second proxy
timeout; listings alone are compressed. Access logs are disabled.
Party state is in memory: a restart clears listings/searches, not links or PBs.
One application process owns this state; do not add workers without shared storage.
Short-code guessing also has bounded per-client and global limits in this process.
Anonymous linking has separate in-process challenge/verification budgets and
reserved lookup capacity for already-linked players; see API.md for limits.
These are single-process admission controls, not distributed DDoS protection.
Do not add workers without shared rate-limit state. Pending-link and established
credential storage budgets are separate; see API.md. Auth startup adds indexes
idempotently and cleans up expired/orphaned credentials without invalidating
valid sessions. Existing database columns and token formats remain compatible.
Deploy the service and nginx config together: nginx overwrites X-Forwarded-For
with the connection address, and Uvicorn trusts proxy headers only from 127.0.0.1.
Never bind the backend publicly or broaden that trust to arbitrary senders.
Held requests use two nginx connections each; size worker_connections accordingly.

Keep auth/record databases and backups outside releases, source control and test
fixtures. See [API.md](API.md).

## Record protocol migration

Back up records.sqlite3 before the first v2 deployment. Startup imports mod_bests
once as eligible legacy records, records the migration, and removes the obsolete
minima table so deleted records cannot be reimported. This is a forward schema
migration: rolling back to the old record writer is not supported. Use a compatible
forward fix; do not restore an old database and resurrect erased or moderated data.

Deploy nginx's records route and its separate 120 requests/minute/IP budget with
the backend. Deploy the ownership-proof exchange first, and complete account erasure
and moderation access configuration before enabling production evidence collection.
Verify old uploads return 410 while existing PBs remain visible. Then install the
updated mod and test live start, progression, finish, disconnect, and two-client
terminal corroboration. Automated tests do not establish live-game correctness.

## Moderation and erasure deployment

Configure MITHRIL_OWNER_UUID as the owner's lowercase, unhyphenated Minecraft UUID.
Do not use a mutable username or put operator identities in test fixtures. The owner
signs in through the ordinary Minecraft link and manages grants at `/moderation`.
Set MITHRIL_PRIVACY_OPERATOR and MITHRIL_PRIVACY_EMAIL to the public operator name
and privacy contact; verify `/api/v1/privacy` before opening registration.

For IP restrictions, generate a dedicated random key of at least 32 bytes in a
service-readable 0600 file outside releases and set MITHRIL_NETWORK_KEY_FILE to its
path. Without a key, IP bans are unavailable; account bans and mutes still work.
Keep that key stable across releases; rotation invalidates existing IP matches.
It is separate from login/API secrets. Install the accompanying nginx configuration:
every proxied location overwrites forwarded addresses, including nested listings.
The loopback-only backend must trust headers only from nginx's loopback address.

Auth and records databases now participate in attached SQLite erasure transactions.
Keep them on the same local filesystem using the default rollback journal; do not
switch either database to WAL or move them to independent database servers without
redesigning atomic erasure. Forward schema migration only: older code cannot safely
serve these databases. Public source, both client/server tests, moderator access,
privacy contact and the erasure path must be ready before collecting live evidence.

Keep database backups private and delete every copy after seven days, including
pre-deployment and off-host copies. Record a UTC creation timestamp with each backup.
`erasures.jsonl` beside auth.sqlite3 is a separate live deletion ledger: preserve it
across releases and database restores. Restrict the directory and ledger to the
service/operator, and preserve a current independent copy for disaster recovery.
Do not replace the live ledger with the version in an old backup. It contains UUIDs
and deletion scope/time, and entries expire after seven days. Missing/damaged required
ledgers fail startup; never discard one just to make the service start.

Restore only backups younger than seven days, with the service stopped. Restore
both auth.sqlite3 and records.sqlite3, preserve the newest erasure ledger, then run:

```text
python tools/replay_erasures.py /var/lib/mithril-web/auth.sqlite3 --backup-created <ISO-8601-UTC-time>
```

The command refuses older backups or missing inputs and reapplies unapplied deletions.
Normal startup also replays the ledger before serving requests. If the current ledger
is lost, do not serve restored personal data until deletions can be reconciled.
A routine code rollback never restores databases or the ledger. Verify an isolated
synthetic backup/erase/restore exercise before enabling production erasure.

## Live PB connection recovery

Deploy the exact-progress retry backend before the corresponding client. No schema
migration is needed; older evidence without a request digest cannot be retried.
Install the nginx upstream `keepalive_timeout 3s` setting so pooled connections are
retired before Uvicorn's five-second idle timeout. Validate nginx before reload.
Exact retries retain the original evidence timestamp and do not recreate erased
or moderated records. Existing authentication and live-evidence limits still apply.

## Replay room counters

Deploy support for the optional replay `room_secrets` stream before releasing a
client that sends it. The former strict reader rejects this field. This adds no
database schema and retains older replay formats. The stored-map read bound is
620 KiB; the existing 640 KiB solo-progress request allowance is sufficient for
maximum position and room-counter streams. Keep a compatible reader deployed.
