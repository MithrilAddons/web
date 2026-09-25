# Visual direction

The website takes inspiration from Linear's restrained dark surfaces and Stripe's
spacing and typography, without copying their branding or adding a marketing-heavy
landing page. The earlier navy/yellow palette is replaced on the website only.

- Background `#101114`, surface `#17181D`, raised surface `#1E2027`.
- Text `#F0F0F3`, secondary text `#A0A2AE`, borders `#2A2C34`.
- Periwinkle `#B4B8FF` for links, focus and small identity details.
- Pale primary buttons; muted green/red only for actual service states.
- System/local fonts only, no font downloads or third-party image requests.
- Static decoration and short button transitions; respect reduced motion.

## Layout

The home page is a short introduction with one primary destination. The
party-finder page is a workspace: heading/status, wide listing area, and a compact
account sidebar. Future filters belong above the listings; party details can use
the secondary area. Do not fill the current empty state with fictional players,
invented activity counts or controls that pretend to work.

On narrow screens the account panel moves above the listing area. Account linking
uses a focused panel; policy pages use a narrower reading column. All routes keep
navigation, the cookie-policy link, visible keyboard focus and a skip link.

Matching, filters, party details and other future screens still need their own
functional design. This change establishes their visual foundation, not their APIs.
