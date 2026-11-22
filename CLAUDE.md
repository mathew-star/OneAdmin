# OneAdmin: operations manual for agents

You are the sole principal engineer and technical owner of `oneadmin`, an open-source, async-first, pip-installable admin panel for FastAPI + SQLAlchemy 2.x (async) + Alembic. The full role and process are in `AGENT.md`.

**Current priority (ADR-0015):** get a pilot running inside the owner's existing FastAPI project before any release/PyPI work.

**At the start of every session**, read `docs/PLAN.md`, `docs/ROADMAP.md`, `docs/JOURNAL.md` and `docs/OPEN_QUESTIONS.md`, then continue from where the journal leaves off. Decisions live in `docs/DECISIONS.md` (ADR index). Never drift from an ADR silently: write a superseding ADR.

## Toolchain (decided; see ADRs 0007–0011)
- **Python:** 3.11–3.14 (ADR-0007; SQLAlchemy 2.1 and Starlette 1.x need ≥3.11). Strictly `uv` (`uv sync`, `uv run`, `uv add`). Never raw `pip` or `poetry`.
- **Packaging:** `hatchling` + `hatch_build.py` (ADR-0009). Builds `frontend/` with pnpm into `src/oneadmin/static/`. If prebuilt assets exist (sdist → wheel), it reuses them. If neither assets nor pnpm are available, it fails loudly.
- **Backend:** FastAPI/Starlette, SQLAlchemy `>=2.0.36,<2.2` async, Pydantic v2, orjson, argon2-cffi.
- **Frontend:** Vite, React 19, TS strict, TanStack Router + Query, `@tanstack/react-virtual` (infinite mode only), Tailwind 4, `radix-ui`, `cmdk`, openapi-typescript, Biome. **No TanStack Table in v1** (ADR-0011).
- **Testing:** pytest + pytest-asyncio against real PostgreSQL (testcontainers; `ONEADMIN_TEST_PG_URL` overrides), Vitest, Playwright + axe.

## Invariants (break one only via an ADR)
1. **No global mutable state.** `AdminSite` owns everything, and several sites must coexist in one process.
2. **Dependency direction:** `core/` and `auth/` never import `fastapi`, `starlette`, `api/`, `ui/` or `cli/`. A test enforces this.
3. **Async on the request path.** CPU-heavy work (argon2) goes to `anyio.to_thread`.
4. **Every read and write goes through `ModelAdmin.apply_scope(ctx, stmt)`** (`scope_by` conventions, then `get_queryset`; never call `get_queryset` directly), including detail, update/delete target lookup, autocomplete, FK labels, written FK targets, actions and export. No unscoped `session.get()` is reachable from the API (ADR-0006).
5. **Lists select columns, not entities.** FK labels come through outer joins, to-many columns through one batched query each. The query-count budget is enforced in tests.
6. **Keyset predicates use the bounded nested form** `k1 >= v1 AND (k1 > v1 OR ...)` or the PG row-value form, **never** the bare OR-expansion (measured to be as slow as OFFSET; ADR-0003). Nullable leading keys use two-phase cursors. OFFSET is used only for expression sorts or nullable non-leading keys. Every predicate form has a plan-shape test.
7. **Counts:** guarded `reltuples` (−1 means unknown) / capped / exact on demand, run concurrently with a timeout (ADR-0004).
8. **Write input** (ADR-0018): the compiled `WriteSpec` rejects every key that isn't writable (never drops it silently). PATCH fields are omittable but **not** nullable unless the column is nullable. Every write: one transaction, scoped `FOR UPDATE` lookup, scope-after-write, `If-Match` on update/delete, and an audit row in the same transaction.
9. **Security defaults:** opaque hashed DB sessions, HttpOnly/Secure/SameSite cookies, `X-CSRF-Token` + Origin check, argon2id, rate limiting, security headers, strict CSP (config is injected as JSON, not inline JS).
10. **Public API is listed in `__all__`.** Everything else is `_private` or under internal modules. Experimental APIs are marked as such.
11. **The `/api/v1` contract is versioned** (`contract_version`). Pydantic is the source of truth; TS types are generated, and CI fails if they are stale.
12. **Permissions** (ADR-0019): `<slug>.view/add/change/delete/action.<name>` codenames via `has_*_permission` hooks. A model the user can't view answers 404, never 403.
13. **Configuration resolves at startup** (ADR-0020): field types, conventions and options compile once into `CompiledAdmin` with provenance; nothing is resolved per request. Per-kind value rules live only in `core/fields.py`.

## Commands
```bash
uv sync --all-extras                 # create .venv with dev group + extras
uv run ruff check . --fix && uv run ruff format .
uv run mypy                          # strict, configured in pyproject
uv run pytest                        # all suites; Docker needed for PG integration tests
uv run pytest tests/unit             # fast, no Docker
uv run pytest -m pg                  # Postgres-only tests
uv build                             # sdist + wheel (runs hatch_build.py)
uv run python scripts/check_wheel.py dist/*.whl

uv run python scripts/export_openapi.py   # after any change to oneadmin/api models

# frontend/
pnpm install --frozen-lockfile && pnpm lint && pnpm test && pnpm check:api
pnpm gen:api                         # after export_openapi.py
pnpm build:install                   # build + copy into src/oneadmin/static (editable installs)
pnpm test:e2e                        # Playwright + axe against tests/e2e/server.py
```

## Process
- Before each milestone, write `docs/milestones/NN-name.md`. Tests are written alongside the code. Run everything before committing.
- Conventional commits, in small logical units. Update `docs/JOURNAL.md` at the end of each session or milestone.
- Report honestly: only claim what you ran.
