# Deployment

Production serves `https://mithril.foo`; www redirects to the root.
The .foo domain requires HTTPS. Serve the frontend and API from one origin,
with the backend bound to loopback behind nginx. Keep other hosted services unchanged.

## Release layout

- `/opt/mithril-web/releases/<release>/`: root-owned source, frontend build and venv.
- `/opt/mithril-web/current`: active release symlink.
- `deploy/mithril-web.service`: unprivileged mithril-web service, loopback port 8780.
- `/var/lib/mithril-web/`: private persistent auth.sqlite3 and records.sqlite3.
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
2. Package only backend source, built frontend and deployment files. Exclude
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
Do not add workers without shared rate-limit state. Existing persistent receipt
and sync-token capacity limits are unchanged by these abuse controls.
Deploy the service and nginx config together: nginx overwrites X-Forwarded-For
with the connection address, and Uvicorn trusts proxy headers only from 127.0.0.1.
Never bind the backend publicly or broaden that trust to arbitrary senders.
Held requests use two nginx connections each; size worker_connections accordingly.

Keep auth/record databases and backups outside releases, source control and test
fixtures. Account-data retention/deletion policy and multi-account/load testing
must be completed before broad distribution. See [API.md](API.md).
