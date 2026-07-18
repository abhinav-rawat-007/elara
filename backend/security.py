"""Access control for Elara's local server.

Elara can run apps, PowerShell, and read files. The only thing standing
between that and the outside world is this WebSocket, so it must not be an open
control channel. Two layers guard it:

1. **Origin allow-list.** A browser always sends a truthful `Origin` header on
   a WebSocket handshake that page JavaScript cannot forge, so any random
   website that tries to reach ws://127.0.0.1:8765 is rejected outright. Only
   the Tauri shell and the local dev server are allowed.

2. **Per-launch token.** The Tauri shell mints a random token, hands it to this
   backend via the ELARA_TOKEN environment variable, and to the webview via an
   `invoke` command — so the real UI can present it and no other local process
   (which an Origin check alone wouldn't stop) can.

Policy (see `authorize`):
  - If a token is configured (packaged app), the token is the gate.
  - If not (developer running the pieces by hand), fall back to the Origin
    allow-list so a stray website still can't drive her.
"""

from __future__ import annotations

import os

# The Tauri webview's origin differs by platform/version; include the dev
# server too. Extend via ELARA_EXTRA_ORIGINS (comma-separated) if needed.
_DEFAULT_ORIGINS = {
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
}


def allowed_origins() -> set[str]:
    extra = os.environ.get("ELARA_EXTRA_ORIGINS", "")
    return _DEFAULT_ORIGINS | {o.strip() for o in extra.split(",") if o.strip()}


def expected_token() -> str:
    return os.environ.get("ELARA_TOKEN", "").strip()


def authorize(origin: str | None, token: str | None) -> bool:
    """Decide whether a WebSocket/HTTP client may connect.

    origin: the request's Origin header (None if absent).
    token:  the token the client presented (e.g. ?token=... query param).
    """
    want = expected_token()
    if want:
        # Packaged app: the token is unforgeable proof this is our own UI.
        return bool(token) and token == want
    # Dev fallback: no token configured. Block foreign websites by origin;
    # allow local, non-browser tooling (which sends no Origin).
    if origin is None:
        return True
    return origin in allowed_origins()
