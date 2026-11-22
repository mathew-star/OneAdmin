"""Request guards for state-changing endpoints (threat model T1: CSRF).

Every unsafe request (POST/PUT/PATCH/DELETE) must pass ``same_origin`` and ``json_body``.
Requests that act on an existing session must also present a valid ``X-CSRF-Token``.
These three layers are independent; each alone stops a classic cross-site form post.
"""

from __future__ import annotations

from collections.abc import Collection
from urllib.parse import urlsplit

from fastapi import Request

from oneadmin.api.errors import ApiError

CSRF_HEADER = "x-csrf-token"


def same_origin(request: Request, trusted_origins: Collection[str]) -> None:
    """Reject requests that a browser marks as coming from another site.

    ``Origin`` is compared by host (and port) against the ``Host`` header rather than by
    full origin. Behind a TLS-terminating proxy the app sees ``http`` while the browser sends
    ``https://``, so a full comparison would break every production login. Hosts in
    ``trusted_origins`` (full origins, e.g. ``https://admin.example.com``) are also accepted.
    Without ``Origin``, fall back to Fetch Metadata. Without either (curl, scripts), allow:
    those clients can't ride a victim's cookies anyway.
    """
    origin = request.headers.get("origin")
    if origin is not None:
        if origin in trusted_origins:
            return
        if origin == "null" or urlsplit(origin).netloc != request.headers.get("host"):
            raise ApiError(403, "cross_origin", "Cross-origin request rejected.")
        return
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        raise ApiError(403, "cross_origin", "Cross-site request rejected.")


def json_body(request: Request) -> None:
    """HTML forms can't send ``application/json``, so requiring it blocks form-based CSRF."""
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(415, "unsupported_media_type", "Send the request body as JSON.")
