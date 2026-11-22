"""Serve the prebuilt SPA under any mount prefix (technical-findings §7).

- ``/assets/*``: content-hashed files with far-future caching.
- Any other path that isn't under ``/api/``: ``index.html``, with
  - ``<base href>`` set from the ASGI ``root_path``, so the build's relative asset URLs
    resolve under ``/admin/``, ``/backoffice/`` or ``/``
  - the runtime config injected as inert JSON (no inline JS, so the strict CSP holds)
  - the site title in ``<title>``

The SPA's client-side router owns every non-API path, so deep links and reloads work.
"""

from __future__ import annotations

import html
import json
import os
import re
from os import PathLike
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
CONFIG_ELEMENT_ID = "oneadmin-config"

_TITLE = re.compile(r"<title>.*?</title>", re.S)

_FALLBACK = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title}</title></head><body><main><h1>{title}</h1>
<p>The OneAdmin UI bundle is missing from this installation. The API is available under
<code>api/v1/</code>. Rebuild the package with the frontend (see README).</p></main></body></html>"""


def mount_ui(
    app: FastAPI,
    *,
    title: str,
    builtin_auth: bool,
    dev: bool = False,
    static_dir: Path = STATIC_DIR,
) -> None:
    """Serve the SPA from ``app``.

    Args:
        title: The site title, used in ``<title>`` and passed to the UI.
        builtin_auth: Whether the UI shows its own login page (``True``) or relies on the
            host application's authentication (a custom ``AuthBackend``).
        dev: Development mode: the UI shows a badge and offers first-run setup.
        static_dir: The built frontend (``index.html`` + ``assets/``). Tests point it
            elsewhere; applications never need to.
    """
    index = static_dir / "index.html"
    template = index.read_text(encoding="utf-8") if index.is_file() else None
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", _ImmutableStatic(directory=assets), name="oneadmin-assets")

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def spa(request: Request, path: str) -> HTMLResponse | JSONResponse:
        if path == "api" or path.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Unknown API route.", "param": None}},
                status_code=404,
            )
        root = request.scope.get("root_path", "").rstrip("/")
        config = {
            "basePath": root or "/",
            "apiBase": f"{root}/api/v1",
            "title": title,
            "auth": "builtin" if builtin_auth else "external",
            "dev": dev,
        }
        body = (
            _FALLBACK.format(title=html.escape(title))
            if template is None
            else render_index(template, root=root, title=title, config=config)
        )
        # index.html changes with every deploy (new asset hashes): always revalidate.
        return HTMLResponse(body, headers={"Cache-Control": "no-cache"})


def render_index(template: str, *, root: str, title: str, config: dict[str, Any]) -> str:
    """Inject ``<base href>``, the config block and the title into the built ``index.html``."""
    # "<" is escaped so no config value can close the script element early.
    blob = json.dumps(config).replace("<", "\\u003c")
    head = (
        f'<head><base href="{html.escape(root, quote=True)}/">'
        f'<script type="application/json" id="{CONFIG_ELEMENT_ID}">{blob}</script>'
    )
    page = template.replace("<head>", head, 1)
    return _TITLE.sub(lambda _: f"<title>{html.escape(title)}</title>", page, count=1)


class _ImmutableStatic(StaticFiles):
    """Static files with far-future caching: asset names are content-hashed by Vite."""

    def file_response(
        self,
        full_path: PathLike[str] | str,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
