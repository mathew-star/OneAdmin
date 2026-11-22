"""Hatch build hook: make sure the compiled admin SPA inside the package is current.

The built UI in ``src/oneadmin/static/`` carries a stamp, ``.source-hash``: a hash of the
``frontend/`` sources it was built from. Resolution order (ADR-0009):

1. ``frontend/`` sources present and the stamp matches them: reuse the build. This is the
   sdist -> wheel path, where Node must not be required, and a no-op rebuild in a checkout.
2. ``frontend/`` sources present and the stamp is missing or different: rebuild with pnpm
   (``pnpm install --frozen-lockfile && pnpm build``) and copy ``frontend/dist`` over. A
   stale UI is never packaged silently.
3. No ``frontend/`` sources but a built UI: reuse it (a trimmed source tree).
4. Otherwise fail loudly: a wheel without its UI must never be produced.

``ONEADMIN_FORCE_FRONTEND_BUILD=1`` always rebuilds.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

STAMP = ".source-hash"
# Build outputs and tool caches: not inputs to the bundle.
_IGNORED_DIRS = {"node_modules", "dist", "test-results", "playwright-report", ".vite"}


def source_hash(frontend: Path) -> str:
    """A stable hash of every input file under ``frontend/`` (paths and contents)."""
    digest = hashlib.sha256()
    for path in sorted(frontend.rglob("*")):
        rel = path.relative_to(frontend)
        if not path.is_file() or _IGNORED_DIRS.intersection(rel.parts):
            continue
        digest.update(rel.as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class FrontendBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        static = root / "src" / "oneadmin" / "static"
        frontend = root / "frontend"
        has_sources = (frontend / "package.json").is_file()
        has_build = (static / "index.html").is_file()
        force = os.environ.get("ONEADMIN_FORCE_FRONTEND_BUILD") == "1"

        if not has_sources:
            if has_build and not force:
                self.app.display_info(f"[oneadmin] using prebuilt UI in {static}")
                return
            raise RuntimeError(
                "oneadmin build: no prebuilt UI at src/oneadmin/static/index.html and no "
                "frontend/ sources to build it from. Build from a git checkout with pnpm "
                "installed, or from an sdist that contains the prebuilt assets."
            )

        wanted = source_hash(frontend)
        stamp = static / STAMP
        if has_build and not force and stamp.is_file() and stamp.read_text().strip() == wanted:
            self.app.display_info("[oneadmin] prebuilt UI matches frontend/ sources")
            return

        pnpm = shutil.which("pnpm")
        if pnpm is None:
            reason = "is out of date with frontend/" if has_build else "is missing"
            raise RuntimeError(
                f"oneadmin build: the prebuilt UI {reason} and `pnpm` is not on PATH to "
                "rebuild it. Install pnpm (https://pnpm.io/installation) or build from the "
                "published sdist."
            )

        self.app.display_info("[oneadmin] building the UI with pnpm")
        subprocess.run([pnpm, "install", "--frozen-lockfile"], cwd=frontend, check=True)
        subprocess.run([pnpm, "run", "build"], cwd=frontend, check=True)

        dist = frontend / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError(
                f"oneadmin build: pnpm build finished but {dist}/index.html is missing"
            )
        if static.exists():
            shutil.rmtree(static)
        shutil.copytree(dist, static)
        (static / STAMP).write_text(wanted + "\n")
