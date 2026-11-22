# M0: Foundation

## Goal
A repo where every later milestone can be built, tested and shipped: tooling, CI, a test DB, packaging proven end to end, and a realistic example domain.

## Tasks
1. `pyproject.toml` (hatchling, uv dependency groups, ruff, mypy strict, pytest config).
2. Package skeleton `src/oneadmin` with `__all__`, `py.typed`, and the layer layout (`core/`, `auth/`, `api/`, `ui/`, `cli/`).
3. `hatch_build.py` per ADR-0009, plus `scripts/check_wheel.py`.
4. Placeholder `frontend/` that produces `dist/index.html`. The real app arrives in M5.
5. Test infra: testcontainers PG fixture (with `ONEADMIN_TEST_PG_URL` override), transactional per-test sessions, query counter, layering test.
6. `examples/shop`: tenant, user, customer, category, product, tag (M2M), order, order line, enum status, JSONB, a nullable column, a composite-PK table. Plus a seed script (`--orders 1000000`).
7. CI workflow: lint, format check, mypy, tests (PG service), build + wheel check.

## Acceptance criteria
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest` all pass locally.
- `uv build` produces an sdist and a wheel; the wheel contains `oneadmin/static/index.html`. Building the wheel from the sdist works with pnpm absent from PATH.
- The layering test fails if `core` imports `fastapi`.
- The seed script loads 1M orders into PG and the time is recorded.
