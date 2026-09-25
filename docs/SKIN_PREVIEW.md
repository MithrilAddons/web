# Account skin preview

The signed-in account card contains a drag/touch-rotatable skin model, wheel/pinch
zoom, without visible instructions or controls. Keyboard arrows rotate/tilt,
+/- zoom and Home resets; the accessible canvas label describes these controls.
Skin failure or missing WebGL leaves the account and logout button usable.

The endpoint `/api/v1/auth/skin` requires the existing browser session and uses
only its verified UUID. It fetches the public Mojang profile and validates the
texture host/path before requesting the PNG over HTTPS. Redirects, arbitrary
URLs, oversized responses and unsupported image dimensions are rejected. No game
access token is involved, and the browser makes no third-party skin requests.

The memory cache holds at most 128 accounts for five minutes, or failures for
30 seconds, with two concurrent upstream fetches. A skin change may take five
minutes plus Mojang's cache to appear. Missing/default profiles without a texture
show an unavailable message instead of pretending an arbitrary skin is yours.

skinview3d 3.4.2 is a feature-specific MIT-licensed dependency for Minecraft UV
mapping, outer skin layers, old 64x32 skins and slim arms. It and Three.js are
lazy-loaded only after a signed-in skin request succeeds (~129 KB compressed).
The normal page bundle does not include the renderer. License notices are shipped
at `/skin-viewer-licenses.txt`; this does not change the project's license.

The render loop is paused: redraw occurs on interaction, size change, visibility
restore and initial loading only. Pixel ratio is capped at two. Logout/unmount
aborts fetching, disposes the viewer and releases its WebGL context. No animation,
analytics or extra cookie is introduced.

## Verification

Run `python tools/check.py`. Pure tests use synthetic profiles, fake fetches and
mocked WebGL; they do not contact Mojang or use live accounts.

For actual browser rendering without signing in, build the frontend and run
`python tools/preview_skin.py`, then open `http://127.0.0.1:8770/party-finder`.
This separate loopback-only fixture server displays a synthetic TestPlayer and
generated skin. It is not included in deployment and is not a production auth
bypass. Check dragging, scrolling, reset, keyboard, resize and narrow layouts.
Actual account/profile resolution still requires a signed-in live browser check.
