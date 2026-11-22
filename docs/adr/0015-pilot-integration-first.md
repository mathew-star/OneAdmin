# 0015: Pilot integration in a real project before any release work

- Status: accepted (owner direction, 2026-11-06). Amends the milestone order in PLAN §3.
- Date: 2026-11-06

## Context
The owner wants OneAdmin plugged into an existing FastAPI backend and tested there **before** any PyPI/deployment work. A real codebase will surface integration problems (pinned dependency versions, existing auth, session factories, model quirks) that the example app cannot.

The first evidence arrived immediately: the owner's candidate projects pin `sqlalchemy==2.0.36` and `fastapi==0.115.5` (Starlette 0.41.3). Our floor was `sqlalchemy>=2.0.40`, which would not have installed. Lowered to `>=2.0.36`; the full suite passes on 2.0.36 + FastAPI 0.115.5.

## Decision
Re-order milestones so the next deliverable is a **pilot**: the smallest end-to-end slice a developer can install from a local path and use in their app.
- Install: `uv add --editable ../OneAdmin` (path dependency), no PyPI.
- Prebuilt UI committed? No: the wheel/editable install builds it via the hatch hook; the pilot README documents `pnpm` as a dev-only prerequisite for the editable install.
- Auth for the pilot: an `AuthBackend` callback that reuses the **host app's** users (no new tables in their DB yet). Built-in users/sessions (M3) come after.
- Scope of the pilot: register models, list (sort/filter/search/keyset/count), detail, read-only. Writes follow once reads are proven in the host app.
- Release work (trusted publishing, docs site, TestPyPI) moves to the very end and is planned only after the pilot report.

## Consequences
- The frontend shell (formerly M5) moves earlier, in a minimal form.
- The pilot runs against the owner's real schema: every failure there becomes a test fixture here.

## Revisit when
After the pilot report.
