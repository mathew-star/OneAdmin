"""Write the admin API's OpenAPI document to ``frontend/openapi.json``.

The frontend generates its TypeScript types from this file (``pnpm gen:api``), so the
Pydantic models in ``oneadmin.api`` stay the single source of truth (CLAUDE.md invariant 11).
``tests/unit/test_openapi_snapshot.py`` fails when the committed file is stale.

Usage::

    uv run python scripts/export_openapi.py          # rewrite the file
    uv run python scripts/export_openapi.py --check  # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from oneadmin import AdminSite

TARGET = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def render() -> str:
    """The OpenAPI document of a site with the built-in login and no models.

    The routes are generic (``/models/{slug}/...``), so no model is needed; the result is
    independent of any application.
    """
    site = AdminSite(session_factory=async_sessionmaker(), secret_key="x" * 32)
    document: dict[str, Any] = site.openapi()
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args()
    expected = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != expected:
            print(
                f"{TARGET} is stale: run `uv run python scripts/export_openapi.py`", file=sys.stderr
            )
            return 1
        return 0
    TARGET.write_text(expected, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
