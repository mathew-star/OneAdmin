# Journal

## 2026-11-06: Session 1 (Phase 0 + Phase 1)

**Did**
- Read the draft spec, AGENT.md and CLAUDE.md. Created the repo (git) and the docs skeleton.
- Landscape research: PyPI/GitHub metadata, issue-tracker mining (sqladmin, Starlette-Admin), and downloading and reading competitor wheels (sqladmin 0.32, starlette-admin 1.0.3, fastadmin 0.10, piccolo-admin 1.14). Measured competitor SPA bundle sizes.
- Experiments on a real PG17 (Docker, 1M rows): keyset predicate forms, NULL semantics, count strategies (`docs/research/experiments/`). Scratch checks: Alembic `include_schemas` behavior, Pydantic `extra=forbid` and omittable-not-nullable.
- Wrote landscape.md, technical-findings.md, design-review.md, PLAN.md and ADRs 0001–0014.

**Learned / surprised**
- **The draft's keyset predicate is as slow as OFFSET** (86 ms / 502k buffers against 0.6 ms / 53). This was the most important finding of the day.
- `reltuples = -1` straight after a 1M-row bulk insert (no autovacuum yet).
- SQLAlchemy 2.1 and Starlette 1.x require Python 3.11.
- FastAdmin ships a 1.04 MB gzip single JS chunk; Piccolo Admin ships 323 KB.

**Next**
- Owner checkpoint (name, license, Python floor, scope cuts).
- Then M0 (foundation) and M1 (query engine).

**Environment notes**
- Research PG container: `oneadmin-research-pg` on port 55432 (throwaway).

## 2026-11-06: Session 1 (continued): M0 foundation + M1 query engine

**Did**
- **M0:**
  - uv project with hatchling, ruff, and mypy --strict (with the pydantic plugin).
  - Package skeleton with layering enforced by `tests/unit/test_layering.py`.
  - `hatch_build.py`, verified on three paths: checkout + pnpm builds; sdist → wheel works with pnpm **absent** from PATH; checkout without pnpm fails loudly.
  - `scripts/check_wheel.py`; a clean-venv install of the wheel works (`oneadmin --version`).
  - Testcontainers PG fixture with savepoint-per-test isolation, a query counter, and the CI workflow (written, **not yet run**: there is no remote).
  - `examples/shop` domain plus a set-based seed: 1M orders in about 80 s.
- **M1:**
  - `core/meta.py` (introspection), `core/coerce.py`, and `core/query/` (sorting, cursor, keyset, paginate, filters, search, counting).
  - 113 tests passing on PG17, and also on SQLAlchemy 2.0.57.
  - Benchmarks are in `benchmarks/README.md`.

**Learned / surprised**
- A plan-shape assertion of just "some Index Cond exists" was too weak. The draft's OR predicate still produced an `Index Cond` on the tenant column, so the mutant passed 1 of 7 cases. The test now requires the Index Cond to mention the **leading sort key**, and the mutant fails all 7.
- SQLAlchemy 2.1's variadic `Select` typing broke `Select[Any]` signatures (added the `AnySelect` alias).
- A fixture-ordering bug (`DROP TABLE` in teardown waiting on the test's open transaction) hung the suite for 10 minutes. Fixed it and added a `lock_timeout=10s` on the test engine so this class of bug fails fast.
- `filterwarnings=error` caught a testcontainers deprecation and an SA PG18 `Computed` warning early, which was useful.
- ruff format also reformats Python code blocks inside `*.md`. It touched the owner's spec, which I reverted; markdown is now excluded.

**Next**
- Owner checkpoint answers (name, license, Python floor, scope).
- M2: `AdminSite`/`ModelAdmin`, `AdminContext`, scoped builder, FK label joins, `/api/v1` read endpoints, contract snapshots.
- Push to a remote so CI actually runs.

## 2026-11-06: Owner direction
- Owner delegated the name: **`oneadmin`** (ADR-0014).
- Owner priority: integrate with an existing FastAPI backend and test before any PyPI/deployment work (ADR-0015; milestones re-ordered: M2 core+read API → M3 minimal UI → P1 pilot).
- Found candidate projects locally (OpsFlow, 9x/restaurntsaas-*, propertyos-saas/backend). The 9x ones pin SQLAlchemy 2.0.36 / FastAPI 0.115.5 / Starlette 0.41.3, so the SQLAlchemy floor was lowered from 2.0.40 to 2.0.36; full suite passes on that combination.
- Waiting on: which project is the pilot.
- Owner picked the pilot: `9x/restaurntsaas-backend` (strictest pins: SQLAlchemy 2.0.36, FastAPI 0.115.5).
- Owner wants Django-style `createsuperuser`. Agreed and designed it (docs/design/developer-experience.md, ADR-0016); built-in auth now comes before the pilot. New order: M2 core + read API → M3 auth + CLI → M4 minimal UI → P1 pilot.

## 2026-11-06: M2 (admin core + read API) and first pilot run
**Did**
- ADR-0017 (SQLAlchemy-first, adapter-ready; the `api` layer is forbidden from importing sqlalchemy).
- `AdminSite`, `ModelAdmin` (compiled at startup with actionable `ConfigurationError`s), `AdminContext`, `AuthBackend`, the read service (one query per page, FK labels joined through the *target admin's scoped* subquery, concurrent count on a second session), the wire format (Decimal → string, ints beyond 2^53 → string), the `/api/v1` contract, errors, security headers, and SPA/fallback serving with `<base href>` + JSON config injection.
- 134 tests passing, including 20 HTTP-level tests: auth, scoping on list/count/detail, FK-label scope leak, sensitive-field exclusion, 400 codes for hostile params, one SELECT per page, cross-site cursor rejection, ETag.
- **Pilot:** mounted into `backend/` (the owner's sample app) with two lines; results in `docs/pilot/2026-11-06-sample-backend.md`.

**Learned**
- `from __future__ import annotations` breaks FastAPI dependencies declared as locally defined `Annotated` aliases: they silently became required *query* params (400 "Field required: ctx"). Removed it from `api/router.py`, with a comment explaining why.
- `docs/superpowers/` (untracked, not mine) describes an Oxyde-ORM backend that doesn't match `backend/`. I left it alone.

**Next**
- M3: built-in admin users, `oneadmin migrate` / `createsuperuser`, login and sessions, CSRF. Then replace `LocalDevAuth` in `backend/`.

## 2026-11-06: M2 review + M3 (built-in auth + CLI)
**Self-review of M2 (fixed before building on it)**
- User options and compiled state shared one namespace on `ModelAdmin`, so a user attribute named `label`/`search`/`meta` would have broken the admin. Moved compiled state into a frozen `CompiledAdmin` (regression test added).
- The list service created the count coroutine before the page ran, so it leaked as "never awaited" if the page failed. `gather` would also have left a sibling query running on a closing session. Now every statement is built before any I/O, and page and count run in a `TaskGroup` with errors unwrapped.

**M3 built**
- `auth/`: tables (Core, own MetaData), packaged Alembic env + `0001`, `passwords.py`, `service.py` (users, login, sessions, rate limit, CSRF derivation), `SessionCookieBackend`, `migrate.py`.
- `api/`: `auth_routes.py` (login/session/logout), `guards.py` (origin + JSON), 503 `admin_not_migrated`, `Retry-After`.
- `cli/`: discovery (`--app` / env / pyproject), `migrate`, `createsuperuser`, `changepassword`, `check` + `core/advisor.py` index advice.
- `oneadmin.alembic.include_object`. User guide in `docs/guide/`, README quickstart, CHANGELOG.
- **167 tests pass.** 24 new security/migration tests and 8 CLI tests.
- Pilot `backend/` switched to the built-in login; see the pilot log.

**Learned / surprised**
- argon2id defaults are 64 MiB per hash, so concurrent logins are a memory-DoS vector. Added a `CapacityLimiter`.
- An IP rate-limit counter that resets on any successful login can be bypassed with the attacker's own account. Only the email counter resets now.
- **Two tests had been passing vacuously.** httpx's cookie jar silently refused a cookie set for the dotless domain `test`, so "revoked token is rejected" got a 401 for the wrong reason. Tests now replay tokens via an explicit `Cookie` header and assert the token works *before* revocation.
- Retry-After was off by one (`int()+1` instead of `ceil`).
- The pilot app's own test suite wipes its dev DB. I ran it without reading its conftest first, which was my mistake. Reseeded; logged in the pilot log.

**Next**
- M4: the UI (login, navigation, list, detail), built into the wheel.

## 2026-11-06: M4 (minimal UI)
**Built**
- `frontend/`: React 19 + Vite 8 + TanStack Router/Query + Tailwind 4 + Radix.
  - login, model index, list (sort/search/filter/cursor pager/counts), detail
  - mobile navigation, light/dark themes
  - URL = state, using the API's own parameter names
- **Types:** `scripts/export_openapi.py` → `frontend/openapi.json` (pytest staleness test) → `openapi.d.ts` (`pnpm check:api`). `FieldSchema.kind` and `CountOut.method` are now `Literal`s, so the UI switches over them exhaustively.
- **Serving:** `spa.py` injects the site `<title>` and the auth mode (`builtin`/`external`); `static_dir` is injectable for tests. 8 serving tests: any prefix, deep links, asset resolution, config escaping, CSP-clean real bundle.
- **Build:** `check-bundle.mjs` enforces ≤150 KB gzip initial JS (now 135 KB) and no inline code. The hatch hook stamps builds with a source hash (ADR-0009 amendment).
- **Tests:**
  - 66 Vitest tests (units + whole-app flows against an in-memory API)
  - 4 Playwright tests with axe against `tests/e2e/server.py` (SQLite, mounted at `/backoffice`)
  - 192 pytest tests
- **CI:** a `frontend` job (lint, types, tests, build, e2e). Still never run: no remote.

**Bugs the new tests found (each now has a regression test)**
- **SQLite + built-in login was broken:** naive vs aware datetimes on the first authenticated request. PG-only auth tests hid it, although the README claims SQLite works for development. Fix: `UTCDateTime`.
- `/schema` moved relation columns to the end of `list_display`.
- "Categorys": naive pluralisation.
- `formatSeconds` didn't zero-pad fractional seconds; "1 rows".
- **Packaging could ship a stale UI** (the hook reused any existing `static/`).

**Learned**
- TypeScript 7 (native) has no JS API, so openapi-typescript fails with it. Pinned TS 6.0.3.
- TanStack Router's default search serialisation JSON-parses values (`?f.id__eq=5` → number). Replaced it with flat string params.
- Fragment links (`href="#main"`) break under an injected `<base href>`: they navigate to the mount root.
- Biome turns on Playwright lint rules once `@playwright/test` is installed. It flagged a helper named `describe`.
- My `pkill -f "uvicorn app.main:app"` matched the shell running it. Use the background-task handle instead.

**Next**
- P1: run the pilot end to end with the owner, then M5 (writes, audit, permissions, actions).

## 2026-11-06: M5 (writes, audit, permissions, actions; backend)
**Decided**
- ADR-0018 (write path) and ADR-0019 (permissions), before any code.
- Input is validated by a compiled `WriteSpec` with explicit per-kind parsers, not generated Pydantic models. It is the same coercion as the read wire format (decimals as strings, integers beyond 2^53, the tz rules), and it reports every field error at once.

**Built**
- Migration `0002`: `oneadmin_grant`, `oneadmin_audit_log` (JSONB on PG).
- `core/write_spec.py`, `core/writes.py` (`WriteService`), `core/versioning.py`, `core/actions.py` (`@action`, `delete_selected`).
- `ModelAdmin` gains:
  - `readonly_fields`, `bulk_delete`
  - permission hooks
  - `clean` / `before_save` / `after_save` / `before_delete`
- **API:**
  - create, patch, delete, actions, history
  - `version`/ETag on detail
  - a per-user `/schema` with `permissions`/`actions`
  - error codes mapped in one table (`WRITE_STATUS`)
  - body limit of 2 MiB
- **CLI:** `createuser`, `grant`, `revoke`, `perms`; `check` lists codenames.
- **Tests:**
  - 46 HTTP write tests on PG: mass assignment, omittable/nullable, every type rule, concurrency, the tenant boundary from every direction, permissions matrix, audit atomicity both ways, redaction, actions, guards
  - 35 `WriteSpec` unit tests
  - SQLite write tests
  - CSRF-on-writes and grants with built-in users
  - CLI permission tests
  - **283 Python tests pass.**
- **Pilot:** the whole write surface was exercised over HTTP in `backend/`; results are in the pilot log.

**Found in self-review / the pilot (fixed, with tests)**
- **Gaps in the FK check:**
  - It only covered columns with a `relationship()`. A plain `ForeignKey` column could point at another tenant's row.
  - It is now driven by `ForeignKey` metadata.
- **Rows an action *creates*** escaped the scope check and the audit.
- **Autoflush errors:** `IntegrityError` and missing-table errors can surface on autoflush, outside an explicit flush. They are now translated once, at the transaction boundary.
- **`If-Match` was accidentally required** at the FastAPI level: an `Annotated` alias with no default makes the header required. It gave 400 instead of 428.
- **Unnamed constraints:** they have no name in metadata (PG calls them `product_sku_key`). The field now comes from PG's `Key (sku)=` detail, and the value is never echoed.
- **`onupdate` columns** (`updated_at`) were writable. They are now read-only.

**Design change from the ADR draft (recorded in ADR-0018)**
- The row version covers the *visible* fields, not all mapped columns. That is what the user saw, and partial updates protect untouched fields anyway.

**Next**
- M6: the editing UI (forms from `writable`/`required`, validation errors per field, conflict resolution with `error.current`, actions with confirmations, row history), command palette, a11y audit. Then release planning (M7).

## 2026-11-06: M6 (editing UI)
**Built**
- `lib/formValues.ts`: draft ⇄ wire per kind (decimals and big integers stay strings, local ⇄ UTC for tz-aware datetimes, blank ⇒ omit on create / null or "" on update).
- `RecordForm`, `FieldInput`, `RelationPicker` (ARIA combobox over the target's scoped list), plus lazy `CreatePage`/`EditPage` routes.
- Detail page: Edit/Delete, history.
- List: Add, selection, `ActionBar`, `ConfirmDialog` (focus starts on Cancel), `Toaster`.
- `ApiClient.patch/delete`; `ApiError.fields/current`; `api/mutations.ts` invalidates everything cached for a model after a write.
- **Server:** `blank_fields` (required text refuses blank values); audit entries have an `id`.
- **Tests:**
  - 87 Vitest tests (10 new editing flows on a stateful fake API)
  - 6 Playwright tests, including create, edit, a two-tab conflict, a bulk action, history and delete, with axe on the form, dialogs and history
  - 284 Python tests
- **Bundle:** initial JS 143 KB / 150 KB; the form is a separate 4 KB chunk.

**Verified the tests can fail**
- Mutating `buildPayload` to send every field failed 5 tests.
- Making the rebase drop the user's edits failed the conflict test.

**Found**
- **Pilot:** an empty title was saved. A `NOT NULL` column accepts `""`, so it took a domain rule (Django's `blank=False` default) to refuse it.
- **Playwright ran spec files in parallel workers against one database**, so the read-only journey saw rows from the editing spec. Fixed with `workers: 1`. M4 only passed because there was a single spec file.
- Biome's a11y rules conflict with the WAI-ARIA combobox pattern (options are deliberately unfocusable). There is one documented suppression.

**Deferred**
- The command palette (cmdk): it doesn't fit the initial budget unless lazy, and it is unclear it's wanted. Logged in OPEN_QUESTIONS.

**Next**
- The owner's pilot pass on `backend/`, then M7 release planning.

## 2026-11-06: Roadmap to 1.0
- The owner asked what would make OneAdmin the admin people pick over sqladmin, Starlette-Admin and FastAdmin, and for extreme, Django-like configurability.
- Wrote `docs/ROADMAP.md`, phases 0–6:
  - ground truth
  - extensibility core (M7)
  - first 5 minutes + PyPI 0.1 (M8)
  - parity (M9)
  - standout features (M10)
  - ecosystem (M11)
  - 1.0
- **Key sequencing decision:** the extensibility core comes *before* 0.1, so the public API shape (field types, typed options, conventions, middleware) is settled before anyone depends on it.
- **Architecture direction:** configure in Python, compile once at startup with provenance (`oneadmin explain`), render a versioned set of blocks in the browser, and keep the core guarantees inside every extension point. To be formalised in ADR-0020 at Phase 1 start.
- No code changed.

## 2026-11-07: M7 (extensibility core, ROADMAP Phase 1)
The owner chose to build first; CI, the license and outside users are deferred.

**Built (ADR-0020)**
- `core/fields.py`: one `FieldType` per kind of value (wire, text and input parsing, cursors, filter operators, sortability, writability, widget). `coerce`/`wire`/`filters`/`write_spec` delegate to it. Plus `EmailField`, `URLField`, `MoneyField`.
- `core/compiler.py`:
  - ordered passes (model → conventions → options) with per-setting provenance
  - typed options (`Post.title`, `.desc()`); `ModelAdmin[M]`
  - `field_types`, `labels`, `ignore_conventions`
- `core/conventions.py` (`oneadmin.conventions`): `readonly`, `hide`, `field_type`, `label`, `filterable`, `scope_by` (fail closed on `None`, autofill on create).
- `ModelAdmin.apply_scope`: the single scoping entry point, with a source-level test enforcing it.
- `core/operations.py`: operation middleware around all eight operations.
- `core/explain.py` + CLI: `oneadmin explain`, `oneadmin schema [--diff]`.
- **Frontend:** `WidgetRegistry` in the router context; email, url and money widgets.
- **Tests:** 329 Python (14 field-type, 14 compiler, 5 `scope_by` on PG, 6 middleware, 4 CLI, 2 invariant); 92 Vitest; 6 Playwright.
- **Bundle:** 143.9 KB.

**Found while building (fixed, with tests)**
- `scope_by` autofill ran after required-field validation, so omitting `tenant_id` was rejected before it could be filled. It now resolves before parsing, in wire form.
- Default convention ids ignored the label text or type, so `label("A", "x")` and `label("B", "x")` collided.
- `list_filter = "status"` passes mypy (a `str` is a `Sequence[str]`); only the runtime "did you forget a comma?" check catches it.

**Design notes**
- A `FieldType` may replace another only within the same kind (or between string and text), checked at startup. A `MoneyField` on a string column is a configuration error, not a runtime surprise.
- Conventions record `file:line` at declaration, so `explain` can point at the exact rule.

**Next**
- ROADMAP Phase 2 (M8): `register_all`, `oneadmin init`, `oneadmin demo`, docs site, benchmarks, PyPI 0.1.

## 2026-11-21: Admin UI refinement
- Refined the signed-in shell, collection overview, tables, forms, and sign-in screen with a warm neutral and deep green design system.
- List footers now show the visible row range and the server's exact, estimated, or capped total. The UI stores the range start in the URL as navigation metadata; it does not send it to the API or claim an absolute position for a cursor opened without that metadata.
- Verified with frontend lint, 94 unit tests, 6 Chromium end-to-end tests (including axe checks), and the production build budget (145.6 KB initial JS gzip). The server API and keyset query contract are unchanged.

## 2026-11-21: Data workspace redesign
- The first refinement looked generic in the sample blog screenshot: serif headings, mint accents, a broad header and a rounded table card distracted from the records. The owner asked for a more distinctive studio-like UI.
- Reworked the signed-in shell and model index as a compact data navigator; the list view is now a full grid with column type cues, tighter spacing, flat controls and a graphite / signal-lime palette in dark mode. The existing range footer and cursor behavior remain.
- Reviewed local Chromium screenshots in dark and light mode. Verified `pnpm lint`, 94 Vitest tests, 6 Chromium e2e tests with axe, and `pnpm build:install` (145.7 KB initial JS gzip).

## 2026-11-21: Record and form screens
- Replaced the old rounded detail card with a flat record field grid, showing column names and types alongside values. Activity now belongs to the same record workspace.
- Shared the record header across detail, create, and edit. Edit breadcrumbs link back to the record; forms distinguish read-only fields and keep save/cancel actions available on long pages.
- Visually reviewed local dark and light Chromium captures of both detail and edit screens. Verified frontend lint, 94 unit tests, 6 Chromium end-to-end tests with axe, and the production build budget (146.1 KB initial JS gzip).

## 2026-11-21: Library maintenance foundation
- Audited the package as a consumer-facing Python library. The existing Ruff, strict mypy, compatibility test matrix, wheel check, and typed top-level API are in place.
- Added contributor, architecture, SQLAdmin migration, and release-process guides. The SQLAdmin page repairs a missing MkDocs navigation target and states that generated conversions need manual review.
- Added a strict MkDocs CI job and a distribution metadata check to the build job. The release guide explicitly says publishing is not configured yet.
- Installed the docs dependency group and ran `mkdocs build --strict` locally; it passed after fixing two links outside the docs tree. Full matrix CI and PyPI release are still pending.

## 2026-11-22: Verification of library maintenance work
- Ruff check, Ruff format check, and strict mypy passed. The unit suite exposed a converter test inconsistency: its generated header contained the phrase `from sqladmin`, so a test looking for leftover imports failed. Reworded the generated header and updated its corresponding assertion; all 176 unit tests then passed.
- The static-file serving test hung inside the filesystem sandbox but passed outside it. The full unit suite also passed outside the sandbox in 2.45 seconds.
- Built both sdist and wheel, checked the wheel's UI/migrations/type marker, and validated both distributions with Twine 7. Twine 6.2 rejected Hatchling's metadata version 2.5; the CI gate now pins Twine 7.0.0, which passed.
- Strict MkDocs build passed. The full local Python suite, including PostgreSQL integration and security tests, passed: 359 tests in 40.95 seconds. The repository has not been published to PyPI; remote CI remains unverified.

## 2026-11-22: CLI and review follow-up
- Replaced the `argparse` command tree with Rich Click, retaining the existing command handlers and site discovery. Top-level and command help now come from the same definitions used for parsing. `createuser --grant` now repeats per codename (ADR-0021).
- Hardened built-in auth: malformed emails count toward IP throttling, and login holds the user row lock through session creation so a concurrent password change revokes that session. PostgreSQL security tests cover both paths.
- Added a random first-run development setup token, printed in the server log and required by the API and UI (ADR-0022). The loopback guard observes the immediate peer, so development servers must remain bound to loopback and must not be exposed through a local reverse proxy.
- Edit forms now keep unsaved draft values when a background query refreshes the row; a frontend regression test covers this.
- Verification: targeted development and CLI help tests (12), full Python suite (363), frontend tests (95), TypeScript typecheck, mypy, Ruff lint/format, Biome lint, generated API type check, strict MkDocs build, `pnpm build:install`, source/wheel build, and wheel content check passed. The initial JavaScript bundle was 146.1 KB gzip against the 150 KB budget.
- Outstanding from the broader review: custom actions can use raw sessions to mutate rows outside selected scope without complete audit coverage; request-size checks rely on `Content-Length`. These require API design work, not a superficial guard.

## 2026-11-22: Write-body limit and action trust boundary
- Replaced the `Content-Length`-only guard with a bounded ASGI middleware that counts received bytes for every unsafe method before route parsing, including authentication routes (ADR-0023). A chunked write without `Content-Length` is rejected at 2 MiB; accepted bodies are replayed intact.
- Reviewed custom-action effects. A post-hoc ORM dirty-state check cannot cover autoflush or direct SQL. Kept the raw session as a trusted application extension point, and made its authorization and audit responsibility explicit in the context and user guide (ADR-0024). A constrained action API remains a candidate before public API stabilization.
- Verified 367 Python tests, Ruff lint and format, strict mypy, strict MkDocs build, source/wheel build, and wheel content check. No frontend sources changed in this slice.

