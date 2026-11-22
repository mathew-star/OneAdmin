"""The committed ``frontend/openapi.json`` must match the live contract (invariant 11).

The frontend's TypeScript types are generated from that file, so a stale snapshot means the
UI is compiled against an API that no longer exists.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_frontend_openapi_snapshot_is_current() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "scripts" / "export_openapi.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (ROOT / "frontend" / "openapi.json").read_text(encoding="utf-8")
    assert committed == module.render(), (
        "frontend/openapi.json is stale: run `uv run python scripts/export_openapi.py` "
        "and then `pnpm gen:api` in frontend/"
    )
