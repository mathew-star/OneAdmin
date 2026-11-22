# 0009: Packaging. Hatchling build hook, prebuilt assets in the sdist

- Status: accepted (to be verified in M0)
- Date: 2026-11-06

## Context
- Wheels must contain the compiled SPA.
- `uv build` builds the wheel *from the sdist*.
- Users and downstream packagers must never need Node.

## Decision
- `hatch_build.py` (custom build hook):
  - **If** `src/oneadmin/static/index.html` exists and `ONEADMIN_FORCE_FRONTEND_BUILD` is unset, use it as is (sdist → wheel path).
  - **Else if** `frontend/` exists, run `pnpm install --frozen-lockfile && pnpm build` and copy `frontend/dist` into `static/`.
  - **Else** fail with an actionable error.
- `static/` is git-ignored and listed as `artifacts` for **both** the wheel and sdist targets. The sdist excludes `frontend/node_modules` but includes the frontend source (for transparency and rebuilds).
- CI asserts that the wheel contains `oneadmin/static/index.html` and at least one hashed JS asset, and that the wheel installs and serves the UI in a clean venv.

## Consequences
- The sdist is larger (it carries the built assets). Acceptable.

## Revisit when
Hatch or uv change the sdist → wheel behavior.

## Amendment (2026-11-06, M4): source-stamped builds
The original rule ("reuse `static/` whenever it exists") could package a **stale UI**: rebuild the frontend, forget to copy it, run `uv build`, and the old bundle ships silently. The hook now stamps the built UI with a hash of the `frontend/` sources (`static/.source-hash`):
- sources present + stamp matches → reuse (this still covers sdist → wheel without Node)
- sources present + stamp differs or is missing → rebuild with pnpm, or fail if pnpm is missing
- no sources + built UI → reuse
- neither → fail

`pnpm build:install` writes the same stamp for editable installs. `scripts/check_wheel.py` also verifies that every asset `index.html` references is in the wheel.

