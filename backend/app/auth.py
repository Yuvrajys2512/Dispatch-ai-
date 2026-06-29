"""Optional API-key auth for the dashboard endpoints (Phase 8).

When ``DISPATCH_API_KEY`` is set in the environment the WebSocket and all
``/api/*`` routes require callers to present it:

* **REST** — ``Authorization: Bearer <key>`` header.
* **WebSocket** — ``?key=<key>`` query parameter (the browser WebSocket API
  cannot send custom headers, so the key goes in the URL).

When the env var is empty (the default) the dependency is a no-op so the
existing test suite and local dev workflow are completely unaffected.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request, status

from app.config import settings


def _require_key(request: Request, key: str | None = Query(default=None)) -> None:
    """FastAPI dependency: validate the API key when auth is configured."""
    expected = settings.dispatch_api_key
    if not expected:
        return  # auth disabled — always pass

    # WebSocket path: key in query string.
    if key == expected:
        return

    # REST path: Bearer token in Authorization header.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# Importable dependency alias for routers.
RequireKey = Depends(_require_key)
