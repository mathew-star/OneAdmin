# 0010: Testing stack

- Status: accepted
- Date: 2026-11-06

## Decision
- **Backend:**
  - pytest 9 + pytest-asyncio 1.x (session loop scope)
  - testcontainers-python `postgres:17-alpine`: one container per session, each test inside a transaction that rolls back (SAVEPOINT pattern)
  - `ONEADMIN_TEST_PG_URL` lets you skip Docker and point at an existing DB
  - httpx `ASGITransport` for the API
- **Query-count** assertions via a SQLAlchemy `before_cursor_execute` event counter fixture.
- **Plan-shape** assertions via `EXPLAIN (FORMAT JSON)`, after an explicit `ANALYZE` on a seeded fixture large enough that the planner prefers indexes.
- **Frontend:** Vitest + Testing Library (jsdom); Playwright (Chromium in CI, all three engines nightly) against the example app; `@axe-core/playwright`.
- **Types:** mypy `--strict`. Pyright isn't run as a second checker (one source of truth, less noise).
- **Lint/format:** ruff for Python; Biome for TS (one fast tool instead of eslint + prettier).

## Consequences
Integration tests require Docker locally. CI uses the service container (or testcontainers).
