# M8: The first five minutes (ROADMAP Phase 2)

Goal: a stranger gets a working, good-looking admin on their own models in under five minutes.

PyPI publishing, CI and the license stay deferred at the owner's request (2026-11-07). The package is made release-ready, but not released.

## Steps
1. **`core/autoconfig.py`:** one set of heuristics that suggests `list_display`, `search_fields`, `list_filter` and `ordering` for a model. Used by `register_all` and `oneadmin init`, so the generated code and the automatic admin always agree.
2. **`admin.register_all(Base)`:** every mapped model (or a list), with suggested options. Single-table-inheritance subclasses are skipped (they share the parent's table and slug); `exclude=` and models already registered are respected.
3. **Dev mode:** `AdminSite(dev=True)` (or `ONEADMIN_DEV=1`):
   - **Loopback only.** Requests from other hosts get 403, which makes it safe to leave on by accident.
   - **No secret key needed.** A fixed development key is used. Its constants are public, but it only signs cursors and derives CSRF tokens, which also need the session token.
   - Plain-HTTP cookies.
   - OneAdmin's tables are migrated automatically on the first request.
   - **First-run setup:** while no admin user exists, the UI offers to create the first superuser. It is dev only; production keeps `createsuperuser`.
4. **`oneadmin init --models app.models [--session app.database:async_session_maker]`:** writes a readable `admin.py` with typed options and conventions, and prints the next steps.
5. **`oneadmin demo`** (extra: `oneadmin[demo]`): a packaged shop.
   - Customers, products, categories, orders, order lines.
   - Seeded on SQLite (default 1,000,000 orders, `--rows`), or on PostgreSQL with `--database`.
   - Runs in dev mode, prints a login, and opens the browser.
6. **Docs site:** MkDocs Material (`mkdocs.yml`; `uv run --group docs mkdocs build --strict`).
7. **Head-to-head benchmark:** `benchmarks/compare/` runs OneAdmin, sqladmin and Starlette-Admin on the same PG data, at page 1, a deep page and the last page; results are published in the docs with the scripts.
8. **"Coming from sqladmin":** a guide plus `oneadmin convert sqladmin FILE`, a codemod from `ModelView` classes to `ModelAdmin`.
9. **Release readiness:** metadata, classifiers, the `demo` extra, and a clean-venv install test of the wheel (`oneadmin demo --rows 1000` runs).

## Acceptance
- From a clean venv with the wheel: `oneadmin demo` gives a browsable 1M-row admin with a login.
- In `backend/`, `register_all` plus dev mode works with no migrate or createsuperuser step; the setup screen creates the first admin.
- Every step has tests, including dev mode's loopback guard and the "setup only while no user exists" race.
