# Technical findings

Each finding is labeled with how it was established:
- **[measured]**: I ran it, and the script is in `experiments/`.
- **[source]**: I read the code or docs.
- **[assumption]**: not yet verified. Each one is tracked in `OPEN_QUESTIONS.md`.

## 1. Versions and support floors (PyPI and npm, fetched 2026-11-06) [source]

| Package | Latest | requires-python |
|---|---|---|
| SQLAlchemy | 2.1.8 | **>=3.11** |
| Starlette | 1.10.0 | **>=3.11** |
| FastAPI | 0.162.0 | >=3.10 |
| Pydantic | 2.14.3 | >=3.10 |
| Alembic | 1.20.1 | >=3.10 |
| asyncpg | 0.32.0 | >=3.9 |
| argon2-cffi | 25.1.0 | >=3.8 |
| pytest 9.2 / pytest-asyncio 1.4.1 / testcontainers 4.15 / hatchling 1.33 / mypy 2.4.1 / ruff 0.17.4 | | |

Frontend (npm): react 19.3.1, vite 8.3.6, typescript 7.0.2, @tanstack/react-router 1.170, react-query 5.106, react-table 9.3, react-virtual 3.14, tailwindcss 4.3.4, radix-ui 1.8.1, cmdk 1.1.1, openapi-typescript 7.13, vitest 5.1, @playwright/test 1.65.

**Consequence:** the draft's "Python 3.10+" target is out of date.
- The SQLAlchemy 2.1 migration notes say 3.10 support was "dropped as of August, 2026", ahead of CPython 3.10's EOL in October 2026, and today is 2026-11-06.
- Starlette 1.x also requires 3.11.
- Supporting 3.10 would pin users to old Starlette and SQLAlchemy 2.0, so the floor becomes **3.11** (ADR-0007).

SQLAlchemy 2.1 notes that matter to us [source: migration_21]:
- `greenlet` is only installed with the `[asyncio]` extra, so we depend on `sqlalchemy[asyncio]`.
- Autoflush now runs before `text()` execution too.
- `Select` typing changed from `Select[Tuple[...]]` to `Select[...]` (PEP 646). Our type hints must work on both 2.0 and 2.1, so we test against both in CI.
- The default PG driver is now psycopg 3. We stay driver-agnostic and test against asyncpg.

## 2. Keyset pagination on PostgreSQL 17 (1M rows) [measured]

Script: `experiments/pg_keyset_and_counts.py`; raw output: `experiments/pg_keyset_and_counts.out.txt`.
- Setup: one table, 1,000,000 rows, composite index `(created_at, id)`.
- Timings are best-of-5 from Python through asyncpg, on a WSL2 laptop with Docker `postgres:17-alpine`. They are only useful for comparing strategies, not as absolute numbers.

| Strategy | Predicate | Time | Buffers | Plan |
|---|---|---|---|---|
| Row-value | `(created_at, id) > (:a, :id)` | **0.62 ms** | 53 | Index Cond on the row comparison |
| Expanded OR (**the draft doc's form**) | `a > x OR (a = x AND id > y)` | **86 ms** | 501,969 | Index Scan with **Filter**: walks half the index |
| Bounded OR | `a >= x AND (a > x OR id > y)` | **0.60 ms** | 54 | Index Cond `a >= x` + filter |
| OFFSET N/2 | `OFFSET 500000` | 86 ms | 501,968 | scans 500,050 rows |
| Mixed direction (`a DESC, id ASC`) | `a <= x AND (a < x OR id > y)` | 0.62 ms | 64 | Index Only Scan + Incremental Sort |

**Findings:**
1. **The draft doc's keyset snippet (§4.3) is as slow as OFFSET.** On PG17 the planner doesn't turn `a > x OR (a = x AND …)` into an index range: it ends up as a Filter, not an Index Cond. Keyset only pays off if the predicate includes a sargable leading bound. Our query compiler must therefore emit:
   - the **row-value form** when every sort key shares one direction and is non-null, or
   - the **bounded form**: `k1 ≷= v1 AND (k1 ≷ v1 OR (k2 ≷= v2 AND (k2 ≷ v2 OR …)))`. This handles mixed directions and works on every dialect.
2. Mixed directions still use the index (an Incremental Sort over the leading key). This came out better than I expected.
3. Because of (1), every predicate shape the compiler emits gets a plan-shape test (`EXPLAIN` must show `Index Cond`) against real Postgres. Wall-clock benchmarks alone are too noisy to catch a regression like this.

### NULLs [measured]
- `(NULL,1) > (0,0)` evaluates to NULL, `(1,NULL) > (0,0)` to TRUE, and `(1,NULL) > (1,0)` to NULL. Row comparisons with nullable keys silently drop rows.
- Putting `OR col IS NULL` into a single predicate (`NULLS LAST`) gives a pure Filter: 1,058 buffers here, and worse deeper in.
- **Decision:** handle a nullable sort key as **two phases** encoded in the cursor: the non-null segment using the bounded form (122 buffers), then the NULL segment (`col IS NULL AND pk > :last`).
  - The cursor stores which phase it is in.
  - Ordering defaults to Postgres semantics (NULLS LAST for ASC, NULLS FIRST for DESC), and we emit explicit `NULLS FIRST/LAST` so the behavior is the same on every dialect.
  - This replaces the draft's "fall back to OFFSET for nullable columns". OFFSET stays only for sorts on computed or non-column expressions.
- PK uniqueness gives the order a total tiebreaker, and the PK is always appended as the last sort key.
- Composite PKs append every PK column.

## 3. Counts [measured]

| Method | Time (1M rows) | Result |
|---|---|---|
| exact `count(*)` | 20.6 ms | 1,000,000 |
| exact filtered (`status='paid'`) | 28.3 ms | 250,000 |
| capped `count(*) FROM (… LIMIT 10001)` | 2.95 ms | 10,001 |
| `pg_class.reltuples` | 0.39 ms | 1,000,000 |
| `EXPLAIN` row estimate (filtered) | 0.96 ms | 253,367 (actual 250,000) |

- **`reltuples` is `-1` on a table that has never been vacuumed or analyzed** (PG14+), including straight after a 1M-row bulk insert. The draft's `SELECT reltuples::bigint` would show "-1 rows". The engine must treat values below 0 as unknown and fall back to a capped count.
- The draft queries `WHERE relname = :table_name`, which is ambiguous across schemas. Use `'schema.table'::regclass` (or `to_regclass`, which returns NULL instead of erroring).
- Exact count on 1M rows is about 20 ms on a warm cache, so it isn't catastrophic at this size. It grows linearly, and with filters, cold caches and wide rows it reaches the seconds reported in Starlette-Admin #686 (2M rows).
- **Strategy (ADR-0004):**
  1. Unfiltered: use `reltuples` if it is ≥ 0 and above a threshold; otherwise run an exact count.
  2. Filtered: run a capped count with the cap configurable (default 10,000).
  3. Add a "count exactly" button. The UI shows "~1.0M" or "10,000+".
  4. Counts run **in parallel with the page query, on a separate connection**, and the count gets a statement timeout. The page never waits on the count.
  5. The `EXPLAIN` estimate is offered as an opt-in strategy for filtered queries. Estimate quality depends on the planner, and it errs on correlated predicates.

## 4. SQLAlchemy introspection and loading [source + assumption]

- **Introspection:** use `sqlalchemy.inspect(Model)` → `Mapper`, which gives:
  - `.column_attrs`, `.relationships` (`.direction`, `.uselist`, `.secondary`, `.local_remote_pairs`)
  - `.primary_key` (a tuple, so composite PKs are natural)
  - `.polymorphic_on` and `.polymorphic_identity`
  - `.all_orm_descriptors` (finds `hybrid_property`)

  Use `Column.type.python_type` with a guarded `NotImplementedError` fallback, since custom types raise it.
- **List views select columns, not entities:** `select(Model.id, Model.email, …)` returns `Row`s, so there is no identity map, no lazy-load trap and no `MissingGreenlet`. FK display labels come from a **joined column** (many-to-one: `LEFT OUTER JOIN` to the target, selecting only its label column). That makes the whole list **one query**, which beats the draft's "2 queries" target.
- **To-many relationships in lists** (e.g. tag names): a second batched query `WHERE parent_id IN (…page pks…)`, i.e. selectin semantics done by hand on column tuples. The budget is 1 + (number of to-many columns) queries, independent of page size.
- **Detail view:** load the entity with `selectinload` for to-many relationships and `joinedload` only for scalar many-to-one, never `joinedload` on collections (sqladmin #704).
- **Edit forms on collection-heavy rows:** load related PKs only (paged), never full collections.
- `AsyncAttrs` and `awaitable_attrs` exist, but the engine never relies on lazy loading. The lazy-load paths it can't avoid get `lazy="raise"`-style guards in tests.
- **Hidden complexity, and the v1 stance on each:**
  - **Composite PKs:** supported. URL pk is an encoded tuple.
  - **Joined/single-table inheritance:** read and list supported. Create is only allowed on concrete mapped classes. [assumption: needs a fixture test]
  - **Association objects (M2M with payload):** shown as an inline of the association class (v1 is read-only, editable later). Plain `secondary` M2M gets a multi-select editor.
  - **Hybrid properties:** shown read-only in lists if they have an expression. Sortable only when `hybrid.expression` exists, and then they are an "expression sort", which falls back to OFFSET.
  - **JSON/JSONB:** JSON editor widget. Not sortable. Filterable by `has_key` later.
  - **Custom TypeDecorators:** use `impl` for the widget, fall back to read-only string, and expose a registry hook that maps a type to a field so users can teach us new types.
  - **Server defaults and computed columns (`Computed`, `Identity`):** excluded from create and update input models.

## 5. Pydantic v2 dynamic models [measured]

Pydantic 2.14.3, tested in a scratch script:
- `create_model(..., __config__=ConfigDict(extra="forbid"))` **rejects unknown keys** (`is_superuser` → ValidationError). This is the mass-assignment defense. It is safer than silently dropping keys because it surfaces mistakes in the client contract.
- For PATCH semantics use `model_fields_set` / `model_dump(exclude_unset=True)`. A field declared `str` with default `None` **rejects an explicit `null`** while still allowing omission, which is exactly what we want for "field is NOT NULL but optional in PATCH". The draft's "wrap every field in `Optional[...] = None`" would let clients write NULL into non-nullable columns.
- Build the models once at registration time and cache them on the `ModelAdmin` instance. Never rebuild per request.

## 6. Session auth for an SPA [source + design]

Rather than write signed or stateless JWT sessions, we use **opaque DB-backed sessions**:
- 32-byte `secrets.token_urlsafe` sent in the cookie. **Only its SHA-256 is stored**, so a DB dump doesn't leak live sessions.
- Idle and absolute expiry. Rotate the token on login and privilege change. Revoke on logout or password change.
- Cookie flags: `HttpOnly; Secure; SameSite=Lax; Path=<mount prefix>`. `Secure` can only be switched off explicitly, for localhost dev, and doing so logs a warning.

CSRF uses defense in depth:
1. **Synchronizer token**: a per-session token returned by `/auth/session` and required in `X-CSRF-Token` on every unsafe method, compared in constant time.
2. **Fetch Metadata / Origin check**: reject unsafe requests whose `Sec-Fetch-Site` is `cross-site`, or whose `Origin` doesn't match the allowed origins.
3. JSON-only bodies (`Content-Type: application/json` is required), so a plain HTML form can't post to the API at all.

Passwords:
- `argon2-cffi` `PasswordHasher()` defaults (argon2id). **Hashing is CPU-bound (tens of ms), so it runs in `anyio.to_thread.run_sync`** to avoid blocking the event loop [assumption: measure the cost on CI hardware].
- `check_needs_rehash` on login.
- Constant-time behavior for unknown users: verify against a dummy hash so timing doesn't reveal which usernames exist.

Rate limiting:
- Login attempts are counted per (normalized username) and per IP in the DB, so the limit works across workers without Redis.
- Exponential backoff and lockout windows. Redis becomes an optional backend later.
- Proxy-aware client IP only when `trusted_proxies` is configured; never trust `X-Forwarded-For` by default.

## 7. SPA under an arbitrary mount prefix [source + assumption]

- `app.mount("/admin", sub_app)` gives the sub-app a `root_path` in the ASGI scope (Starlette). The SPA can't know the prefix at build time.
- **Approach:**
  - build Vite with `base: "./"` (relative asset URLs)
  - serve `index.html` through a handler that injects `<base href="{root_path}/">` and a JSON config blob (`<script type="application/json" id="oneadmin-config">`, not an inline executable script, so we stay compatible with a strict CSP: `script-src 'self'`)
  - TanStack Router reads `basepath` from that config
- Hashed assets get `Cache-Control: public, max-age=31536000, immutable`. `index.html` gets `no-cache`.
- [assumption] Precompressed `.br`/`.gz` siblings, served by the sub-app based on `Accept-Encoding`, to be verified in milestone M5.

## 8. Wheel bundling with Hatch [source + assumption]

- Hatch `artifacts` includes VCS-ignored files (the built `static/`) and must be set **per target (wheel and sdist)**.
- Build hooks run for each target.
- `uv build` builds the sdist first and then **builds the wheel from that sdist** [assumption: verify in M0]. So:
  - The sdist must contain the built `static/`.
  - When `frontend/` is absent (we are inside an sdist) or the assets are already present, the hook must skip pnpm.

  Otherwise anyone building from the sdist would need Node, which breaks the "no Node for users" promise.
- The hook must **fail loudly** if neither prebuilt assets nor pnpm are available. A wheel without its UI must never ship silently. CI asserts that `static/index.html` is in the wheel.

## 9. Release: PyPI trusted publishing [source, recalled; re-verify at release time]

- GitHub Actions OIDC (`permissions: id-token: write`) with `pypa/gh-action-pypi-publish`. No API tokens.
- Use a protected `pypi` environment. PEP 740 attestations are generated by the action by default.
- Build once in a separate job, upload the artifact, and publish from a job that has only the publish permission.

## 10. Alembic coexistence [measured]

Scratch test with alembic 1.20.1 and `compare_metadata`:
- With the default `include_schemas=False`, tables in another schema (`oneadmin.admin_user`) are **not** reported for removal, so the user's autogenerate leaves the admin tables alone.
- With `include_schemas=True`, autogenerate **proposes dropping the admin tables**. That is a real footgun.

Mitigations:
1. Ship an `include_object` helper (`oneadmin.alembic.exclude_admin_tables`).
2. Ship our own migrations as an Alembic **branch** with its own version table (`oneadmin_alembic_version`), applied by `oneadmin migrate`.
3. Document both.

The draft's dedicated-schema idea doesn't work on SQLite or MySQL, where a schema means a separate database. Table names are therefore prefixed (`oneadmin_*`), and the schema is optional and Postgres-only.

## 11. Things the draft gets wrong, collected

1. The keyset snippet is index-hostile (§2).
2. `reltuples` can be -1 and `relname` lookup is schema-ambiguous (§3).
3. The update model wraps everything in `Optional`, so NULL gets written to NOT NULL columns (§5).
4. A dedicated schema is not portable (§10).
5. "Exactly 2 queries" for a list with 3 FKs: 1 is achievable with column selection plus outer joins (§4).
6. "P95 < 45 ms on CI" is a guess, not a measurement. CI runners are too noisy for wall-clock gates, so we gate on plan shape and query count and benchmark separately.
7. The draft's `hatch_build.py` doesn't handle building from an sdist, and its `Any` import is missing (§8).
8. The Python 3.10 floor (§1).
9. "Orval-generated Axios clients" add weight. `openapi-typescript` (types only) plus a roughly 1 KB fetch wrapper is enough.
10. Monaco for JSON is about 2 MB, so we use CodeMirror 6, lazy-loaded.
11. Virtualizing a 50-row page brings no benefit and hurts accessibility (screen readers, Ctrl+F). We virtualize only when the loaded row count exceeds a threshold (infinite-scroll mode).
