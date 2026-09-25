# Web implementation plan

## Foundation

- [x] Separate frontend/backend directories and shared synthetic contract fixture.
- [x] Honest development landing page and versioned, read-only health endpoint.
- [x] Locked dependencies, formatting, linting, automated tests, and CI definition.
- [ ] Publish the initial signed branch/PR and observe both CI jobs.
- [ ] Add the observed CI jobs to required checks (owner authorization required).
- [ ] Select a project license and security reporting channel with the owner.

## Product work still to design and implement

- [ ] Agree on party browsing, queue/filter, profile, and party-detail layouts.
- [x] Initial account verification in Minecraft with remembered browser sessions.
- [ ] Verify live linking, browser restart, and logout with the owner.
- [ ] Versioned shared website/mod protocol and reconnect/session behavior.
- [ ] Server-owned queue, reservations, party membership, and state transitions.
- [ ] Extract and test existing matching logic; never trust editable local PB files.
- [ ] Define record provenance, minimum samples, and verified/unverified presentation.
- [ ] Storage/migrations, retention/deletion, rate limits, abuse controls, monitoring.
- [ ] Connect the independent mithrilpf mod without Noamm/SkyHanni dependencies.

The landing page is not a working party finder. The old development relay and
party-finder test service remain separate; their device overrides and synthetic
records are not public authentication or production data. Do not expose them as such.
