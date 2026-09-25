# Deployment foundation

Target: existing Hetzner server, alongside (not replacing) Atlas and the development
relay. Public host: `https://mithril.foo`; `www` redirects to it. `.foo` requires
working HTTPS in browsers. DNS is managed at Porkbun: root A points to the server,
`www` CNAME points to `mithril.foo`. There is no wildcard or AAAA record.

This deployment exposes the website, health, and versioned account-linking API.
It does not expose matching or accept gameplay records yet.

## Manual release layout

- `/opt/mithril-web/releases/<release>/`: root-owned code, built frontend, and Python venv.
- `/opt/mithril-web/current`: symlink to the selected release.
- Dedicated unprivileged `mithril-web` user runs `deploy/mithril-web.service`.
- API listens only on `127.0.0.1:8780`; nginx exposes health and `/api/v1/auth/`.
- `StateDirectory=mithril-web` owns `/var/lib/mithril-web/auth.sqlite3` with mode 0700
  on its parent. It persists across release changes and service restarts. Never
  copy it into source control, releases, fixtures, or public artifacts.
- Authentication requests are limited by nginx to 30/minute/IP with a burst of 15;
  bodies are limited to 4 KiB. No access logs, cross-origin API access, or redirects
  from Mojang verification requests. Do not expose the backend port publicly.
- `/etc/nginx/sites-available/mithril.foo`: `deploy/nginx.conf`, linked into sites-enabled.
- `/var/www/mithril-web-acme`: webroot for certificate challenges.
- Certbot certificate named `mithril.foo`, covering both root and www.

Before deployment run all checks. Build the frontend locally, export production
Python dependencies with `uv export --locked --no-dev --no-emit-project`, and install
that export in the release venv using pip with `--require-hashes`. Do not upload
local virtual environments, credentials, node_modules, or the Git directory.

For first certificate issuance use `deploy/nginx-bootstrap.conf`, verify `nginx -t`,
then reload nginx. Obtain the certificate using Certbot's webroot authenticator
and the existing server account. Replace the bootstrap with the final TLS config,
verify `nginx -t`, and reload. Certificate renewal needs a deploy hook to reload nginx.
Never restart or rewrite the other hosts as part of this setup.

Release changes are manual: create a new release, point current to it, restart only
mithril-web, and verify HTTPS and health. Keep the previous release for rollback;
point current back and restart the service if necessary. Leave the auth database
in place when rolling back. The initial schema only creates an isolated auth table;
future schema changes require a migration/backup policy. Backups contain account
data and need the same access restrictions and a separately defined retention policy.

Check the root and www HTTPS responses, unknown API routes, certificate renewal,
and the existing Atlas/relay hosts after nginx changes. Source/unit tests alone do
not prove deployment health. CI has no deployment credentials and does not publish.
