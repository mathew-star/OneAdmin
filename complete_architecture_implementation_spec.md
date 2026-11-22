# NexusAdmin: Architecture, Engineering Specification & Implementation Plan
**High-Performance Async Admin Panel Library for FastAPI + SQLAlchemy 2.0**

---

## 1. Executive Summary & Architectural Positioning

### 1.1 The Thesis
Traditional Python administrative dashboards (such as `django-admin` or `sqladmin` or `Fastadmin`) rely on synchronous or pseudo-async Server-Side Rendering (SSR) via Jinja2/WTForms. This introduces structural problems in high-scale asynchronous architectures:
- **Event-Loop Starvation:** Server CPU cycles are spent rendering string templates instead of multiplexing I/O.
- **SQLAlchemy 2.0 Violations:** Accessing relationship properties within template rendering blocks triggers `MissingGreenlet` errors unless eager loading is redundantly defined everywhere.
- **Latency & Bloat:** Every sort, filter, or page change causes full DOM destruction, full-page reloads, uncompressed asset transfers, and uncachable layouts.

`NexusAdmin` eliminates this paradigm by decoupling administrative metadata from UI rendering:
1. **Contract-Driven Backend:** A lean, async-native Python core that inspects SQLAlchemy declarative models, generates cached runtime metadata, compiles dynamic Pydantic v2 validation models, and exposes secure, high-throughput REST endpoints.
2. **Zero-Latency Headless UI:** An un-opinionated, compiled React 19 SPA running TanStack Table, Virtualization, and Query, using URL query parameters as state.
3. **Hermetic Single-Wheel Distribution:** The compiled client assets are packaged directly into the Python wheel via `hatchling` and orchestrated with `uv`. End users install one dependency via pip/uv and require zero Node.js/pnpm infrastructure on target environments.

---

## 2. System Architecture & Component Interactions

```
+---------------------------------------------------------------------------------------+
| Browser Client (React 19 / TanStack Virtual / TanStack Query SPA)                     |
+-------------------------------------------+-------------------------------------------+
                                            | JSON API / Cookie Auth / CSRF Token
                                            v
+---------------------------------------------------------------------------------------+
| FastAPI ASGI Server (Mounted at mount_path="/admin")                                  |
|                                                                                       |
|  +---------------------------------------------------------------------------------+  |
|  | NexusAdmin Sub-Application (ASGI Router Engine)                                 |  |
|  |                                                                                 |  |
|  |  [ StaticFiles Router ] --------> Serves /dist assets (Immutable Cache-Control) |  |
|  |  [ SPA Fallback Catch-all ] ----> Serves index.html with runtime injected config |  |
|  |                                                                                 |  |
|  |  [ API Router: /api/v1 ]                                                        |  |
|  |    +-- Middleware: SessionAuth -> CSRFCheck -> RateLimiter -> TenantContext     |  |
|  |    +-- Endpoints:                                                               |  |
|  |          /schema           (ETag-cached schema contract)                        |  |
|  |          /auth/*           (Login, logout, session status)                      |  |
|  |          /{model}          (QueryBuilder: column subset, keyset cursor, search) |  |
|  |          /{model}/{pk}     (Pydantic validate -> unit of work -> audit log)     |  |
|  |          /actions/{action} (Bulk execute with batch size caps)                  |  |
|  |          /export/{format}  (Streaming CSV / NDJSON generator)                   |  |
|  +---------------------------------------------------------------------------------+  |
+-------------------------------------------+-------------------------------------------+
                                            | AsyncSession (Pooled)
                                            v
+---------------------------------------------------------------------------------------+
| Database (PostgreSQL 14+ / MySQL 8+ / SQLite 3.38+)                                   |
|   +-- User Application Tables                                                         |
|   +-- NexusAdmin Tables: nexus_user, nexus_session, nexus_audit_log (Isolated Schema)  |
+---------------------------------------------------------------------------------------+
```

---

## 3. Developer Experience (DX) & Public Interface

The library provides zero-boilerplate bootstrapping with opt-in granular controls.

### 3.1 Bootstrap Example
```python
# main.py
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus_admin import AdminSite, ModelAdmin
from app.models import Base, Order, Product, User

engine = create_async_engine(
    "postgresql+asyncpg://app:secret@localhost:5432/production",
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False)

admin = AdminSite(
    title="Nexus Production Core",
    session_factory=session_factory,
    base_path="/admin",
    secret_key="env-loaded-super-secret-key",
)

@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ("id", "email", "role", "is_active", "created_at")
    list_filter = ("is_active", "role", "created_at")
    search_fields = ("email", "^username")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")
    exclude = ("hashed_password",)
    
    # Tenancy / Authorization scoping hook
    async def get_queryset(self, request, base_query):
        if not request.state.user.is_superuser:
            return base_query.where(User.organization_id == request.state.user.org_id)
        return base_query

@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ("id", "user_id", "total_amount", "status", "created_at")
    list_select_related = ("user",)  # Eager-loads user: prevents N+1 queries
    autocomplete_fields = ("user",)
    show_full_count = False           # Uses relational planner estimation

app = FastAPI()
admin.mount(app)
```

---

## 4. Backend Engine Technical Specification

### 4.1 Introspection Engine (`nexus_admin.introspection`)
Introspection executes strictly once per model registration. The generated metadata is cached in immutable dataclasses.

```python
from dataclasses import dataclass
from typing import Any
from sqlalchemy.orm import Mapper

@dataclass(frozen=True, slots=True)
class FieldMeta:
    name: str
    python_type: type
    sa_type: str
    widget: str
    nullable: bool
    has_default: bool
    primary_key: bool
    max_length: int | None
    enum_values: list[str] | None
    fk_target: str | None
    readonly: bool

@dataclass(frozen=True, slots=True)
class RelationshipMeta:
    name: str
    target_key: str
    direction: str  # MANYTOONE, ONETOMANY, MANYTOMANY
    uselist: bool
    foreign_keys: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ModelMeta:
    key: str                # e.g., "accounts.User"
    class_ref: type
    table_name: str
    pk_field: str
    fields: dict[str, FieldMeta]
    relationships: dict[str, RelationshipMeta]
```

#### Mapping Matrix: SQLAlchemy Types to Frontend Contract
| SQLAlchemy Column Type | Python Type | Widget Identifier | Coercion Handler |
| :--- | :--- | :--- | :--- |
| `String`, `VARCHAR` | `str` | `"text"` | `str(val)` |
| `Text` | `str` | `"textarea"` | `str(val)` |
| `Integer`, `BigInteger`, `SmallInteger` | `int` | `"number"` | `int(val)` |
| `Numeric`, `Float`, `DECIMAL` | `float` / `Decimal` | `"decimal"` | `float(val)` |
| `Boolean` | `bool` | `"checkbox"` | `bool(val)` |
| `DateTime(timezone=True/False)` | `datetime` | `"datetime"` | `.isoformat()` |
| `Date` | `date` | `"date"` | `.isoformat()` |
| `UUID` (Native/CHAR) | `uuid.UUID` | `"uuid"` | `str(val)` |
| `Enum` (PEP-435 / Database native) | `enum.Enum` | `"select"` | `str(val.name)` |
| `JSON`, `JSONB` | `dict` / `list` | `"json"` | Passthrough dict |
| `ARRAY` | `list` | `"array"` | Passthrough list |
| Foreign Key reference | Target PK type | `"fk_autocomplete"` | Target PK coersion |

*Edge Case Handling:* Any unrecognized dialect column type gracefully degrades to `"readonly_fallback"` with raw string serialization, preventing fatal bootstrap failures.

---

### 4.2 Dynamic Validation Engine (`nexus_admin.pydantic_factory`)
Instead of WTForms or manual serialization checks, dynamic models are compiled via Pydantic v2 `create_model`:

1. **Read Model:** Includes all introspected fields and computed `list_display` callables.
2. **Create Model:** Contains all non-PK, non-generated fields. Non-nullable columns without database defaults are marked `...` (required).
3. **Update Model:** Derives from the Create model, wrapping every field in `Optional[...] = None` to support atomic `PATCH` semantics.
4. **Mass Assignment Protection:** Fields marked in `exclude` or `readonly_fields` are purged from the accepted input schemas at model compile time.

---

### 4.3 High-Performance Dynamic Query Engine (`nexus_admin.query`)
The query pipeline constructs pure SQLAlchemy 2.0 AST queries, avoiding raw SQL string interpolation.

#### Keyset Cursor Pagination
Standard `OFFSET / LIMIT` pagination exhibits $O(N)$ execution time as offset scales, due to table scanning overhead. `NexusAdmin` defaults to Keyset (Seek) Pagination ($O(1)$ performance):

```python
# Keyset condition logic for sorting by [Col_A DESC, Col_PK DESC]
# Cursor shape: base64(json_dumps([last_val_a, last_pk]))
from sqlalchemy import tuple_, and_, or_

def apply_keyset_cursor(query, sort_column, pk_column, cursor_vals, descending=True):
    val_a, val_pk = cursor_vals
    if descending:
        return query.where(
            or_(
                sort_column < val_a,
                and_(sort_column == val_a, pk_column < val_pk)
            )
        )
    return query.where(
        or_(
            sort_column > val_a,
            and_(sort_column == val_a, pk_column > val_pk)
        )
    )
```

#### Safe Filtering Matrix
Filters enforce strict whitelist validation against model attributes:
- `eq`, `ne`, `gt`, `gte`, `lt`, `lte`
- `in` (comma-separated, type-cast to sequence)
- `like`, `ilike` (automatically escapes `%` and `_` characters from incoming payloads)
- `isnull` (boolean validation)

#### Low-Overhead Counts
When loading large tables ($> 100,000$ rows):
1. **Unfiltered Queries:** For PostgreSQL, read tuple statistics from the system catalog:
   ```sql
   SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname = :table_name;
   ```
2. **Filtered Queries:** Query counts are capped using subquery evaluation:
   ```sql
   SELECT count(*) FROM (SELECT 1 FROM target_table WHERE ... LIMIT 10001) AS sub;
   ```
   If count reaches `10001`, the client displays `"10,000+"` rows, safeguarding against long count scans.

---

### 4.4 Authentication, Sessions & Auditing

#### Isolated Metadata
Admin state does not pollute the application's business tables. NexusAdmin initializes an independent `MetaData(schema="nexus_admin")` namespace:
- `nexus_user`: Admin identity, Argon2id-hashed passwords, role definition, active status.
- `nexus_session`: Cryptographically random UUID sessions stored in DB (or Redis), with configurable idle and hard expirations.
- `nexus_audit_log`: Append-only audit records.

#### Atomic Audit Log Pattern
Audits are written within the same database transaction boundary as the model operation. If a transaction fails or rolls back, the audit log rolls back with it, eliminating false-positive audit trails:

```python
async def mutate_with_audit(
    session: AsyncSession,
    model_instance: Any,
    action: str,
    actor_id: str,
    diff: dict[str, Any],
    ip: str,
):
    session.add(model_instance)
    audit = NexusAuditLog(
        actor_id=actor_id,
        target_model=model_instance.__class__.__name__,
        target_pk=str(model_instance.id),
        action=action,
        diff=diff,  # JSONB: {"field": [old_val, new_val]}
        ip_address=ip,
    )
    session.add(audit)
    await session.commit()
```

---

## 5. Frontend Architecture & Technology Stack

```
frontend/src/
+-- core/
|   +-- api/            # Orval-generated Axios/Fetch clients against OpenAPI v1
|   +-- auth/           # Session context, CSRF token managers
|   +-- router/         # TanStack Router programmatic route definition
|   +-- theme/          # Tailwind theme configurations (Dark/Light mode)
+-- schema/
|   +-- types.ts        # Contract schema interfaces (mirrors Python SchemaBuilder)
|   +-- useSchema.ts    # React Query caching layer with ETag support
+-- features/
|   +-- table/
|   |   +-- DataTable.tsx           # TanStack Table virtualized with @tanstack/react-virtual
|   |   +-- ColumnHeaderFilter.tsx  # Dynamic filter inputs based on field type
|   |   +-- KeysetPagination.tsx    # Forward/backward cursor controls
|   +-- form/
|   |   +-- SchemaForm.tsx          # Dynamic React Hook Form mapped to schema
|   |   +-- widgets/                # Text, Int, FK-Autocomplete, JSONEditor, DateTime
|   +-- command/
|       +-- CommandPalette.tsx      # cmdk global navigation (Cmd+K)
+-- App.tsx
+-- main.tsx
```

### 5.1 Frontend Performance Guidelines
- **Bundle Target:** $\le 150 \text{ KB}$ gzipped initial chunk.
- **Dynamic Chunking:** Code-split heavy widgets:
  - JSON Code Editor (`@monaco-editor/react` or `@codemirror/lang-json`) loads only when a model with a JSON field is accessed.
  - Export engines and chart components are lazily fetched on demand.
- **Rendering Strategy:** Virtualized windowing using `@tanstack/react-virtual`. Only the rows visible within the viewport (plus an overscan margin of 5 items) exist in the DOM tree, guaranteeing stable 60 FPS scrolling on datasets of any length.

---

## 6. Monorepo & Packaging Toolchain (Strict `uv` Standard)

The repository layout uses `uv` for workspace management, dependency isolation, and executing Python tooling.

### 6.1 Directory Structure
```
nexus-admin/
+-- pyproject.toml              # Root metadata and build definitions
+-- uv.lock                     # Universal deterministic lockfile
+-- hatch_build.py              # Build hook: Compiles frontend and moves assets
+-- README.md
+-- src/
|   +-- nexus_admin/
|       +-- __init__.py
|       +-- py.typed
|       +-- site.py
|       +-- model_admin.py
|       +-- introspection/
|       +-- query/
|       +-- schema/
|       +-- auth/
|       +-- static/             # Target directory for Vite static output (bundled in wheel)
|           +-- index.html
|           +-- assets/
+-- frontend/
|   +-- package.json
|   +-- pnpm-lock.yaml
|   +-- vite.config.ts
|   +-- tsconfig.json
|   +-- src/
+-- tests/
|   +-- unit/
|   +-- integration/
|   +-- benchmarks/
+-- examples/
    +-- basic_app/
```

### 6.2 Build Orchestration (`pyproject.toml`)
The packaging configuration uses `hatchling` as the build backend, while development workflows, locking, and environment management run through `uv`.

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "nexus-admin"
version = "0.1.0"
description = "High-performance async admin panel library for FastAPI and SQLAlchemy 2.0"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [{ name = "Nexus Core Team" }]
dependencies = [
    "fastapi>=0.110.0",
    "sqlalchemy[asyncio]>=2.0.25",
    "pydantic>=2.6.0",
    "orjson>=3.9.12",
    "argon2-cffi>=23.1.0",
    "python-multipart>=0.0.9",
    "itsdangerous>=2.1.2",
]

[project.optional-dependencies]
redis = ["redis[hiredis]>=5.0.1"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "testcontainers[postgresql]>=3.7.1",
    "httpx>=0.27.0",
    "ruff>=0.3.0",
    "mypy>=1.8.0",
]

[tool.hatch.build.targets.sdist]
exclude = [
    "frontend/node_modules",
    "frontend/src",
    ".github",
    "tests",
]

[tool.hatch.build.targets.wheel]
packages = ["src/nexus_admin"]
artifacts = ["src/nexus_admin/static/**"]

[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
```

### 6.3 Custom Build Hook (`hatch_build.py`)
This hook guarantees that running standard build tools or `uv build` generates the production frontend bundle and copies it directly into the Python package source tree before wheel packing:

```python
import os
import shutil
import subprocess
from pathlib import Path
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        frontend_dir = root / "frontend"
        static_dest = root / "src" / "nexus_admin" / "static"

        if os.environ.get("NEXUS_ADMIN_SKIP_FRONTEND_BUILD") == "1":
            return

        # Ensure dependencies and production build
        subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=frontend_dir, check=True)
        subprocess.run(["pnpm", "run", "build"], cwd=frontend_dir, check=True)

        # Sync dist contents to wheel static payload directory
        dist_src = frontend_dir / "dist"
        if static_dest.exists():
            shutil.rmtree(static_dest)
        shutil.copytree(dist_src, static_dest)
```

---

## 7. Implementation Roadmap & Milestones

```
Timeline: 16 Weeks (Part-time) / 8 Weeks (Full-time)

[Week 1-2]  Phase 0: Foundation & Schema Contract
[Week 3-4]  Phase 1: Introspection & Pydantic Dynamic Factory
[Week 5-7]  Phase 2: High-Performance Query Engine & Keyset Pagination
[Week 8-9]  Phase 3: Auth, Sessions, Security & Audit Logging
[Week 10-12] Phase 4: Frontend Development (React 19 + TanStack)
[Week 13-14] Phase 5: Hermetic Packaging, Static Mount & CLI
[Week 15]   Phase 6: Benchmarks, Hardening & Verification
[Week 16]   Phase 7: Documentation, Examples & Public Launch
```

### Phase 0: Foundation & Schema Contract (Weeks 1-2)
- [ ] Initialize repository with `uv init` and lock development toolchain.
- [ ] Configure `ruff` (linter/formatter) and `mypy` in strict mode.
- [ ] Construct the definitive JSON Schema Specification representing model metadata.
- [ ] Implement synthetic multi-relational test fixtures: User, Tenant, Order, Product, Category, and Tag.
- [ ] Seed script targeting 1,000,000 orders and 50,000 users for local performance profiling.

### Phase 1: Introspection & Pydantic Dynamic Factory (Weeks 3-4)
- [ ] Implement `ModelInspector` extracting columns, constraints, nullability, defaults, and relationships.
- [ ] Implement fail-safe fallback mapping for unknown SQLAlchemy custom/vendor types.
- [ ] Implement `pydantic_factory` generating `ReadModel`, `CreateModel`, and `UpdateModel` per registered model.
- [ ] Implement unit test suite verifying schema generation across all standard SQLAlchemy 2.0 column variants.

### Phase 2: High-Performance Query Engine (Weeks 5-7)
- [ ] Implement dynamic query constructor targeting explicit column subsets (avoiding generic `SELECT *`).
- [ ] Implement cursor-based pagination utilizing composite row comparison `(sort_col, pk) < (:val, :pk)`.
- [ ] Implement fallback to offset pagination for nullable or complex sort fields with warnings.
- [ ] Add eager loading builders matching `list_select_related` to eliminate N+1 queries.
- [ ] Implement Postgres planner-based approximate count strategies (`reltuples`).
- [ ] Validate SQL performance profiles with `EXPLAIN (ANALYZE, BUFFERS)` against 1,000,000-row test instances.

### Phase 3: Auth, Sessions, Security & Audit Logging (Weeks 8-9)
- [ ] Define standalone admin metadata schema (`nexus_admin`).
- [ ] Implement Argon2id password hashing backend via `argon2-cffi`.
- [ ] Implement database-backed secure session engine with signed, Lax/Strict, HttpOnly cookies.
- [ ] Implement CSRF verification system (`X-CSRF-Token` headers for mutating requests).
- [ ] Implement atomic audit log writer binding change diffs to the active unit of work.
- [ ] Add CLI commands via Typer/Argparse: `uv run nexus-admin createsuperuser`.

### Phase 4: Frontend Development (Weeks 10-12)
- [ ] Scaffold `frontend/` using Vite + React 19 + TypeScript.
- [ ] Implement contract consumption layer generating TanStack Query hooks.
- [ ] Implement `DataTable` integrating `@tanstack/react-table` with `@tanstack/react-virtual`.
- [ ] Implement dynamic dynamic form engine matching field widgets to validation constraints.
- [ ] Implement global command palette (`cmdk`) supporting search, route traversal, and actions.
- [ ] Implement responsive Dark/Light UI theme using Tailwind CSS and Radix UI primitives.

### Phase 5: Hermetic Packaging & Mounting Engine (Weeks 13-14)
- [ ] Implement custom `hatch_build.py` connecting `pnpm build` with Hatch packaging targets.
- [ ] Implement `AdminSite.mount(app, path="/admin")` mounting StaticFiles and API routes.
- [ ] Implement runtime injection of application configuration into `index.html` (e.g. `window.__NEXUS_CONFIG__`).
- [ ] Verify clean execution in isolated environments via `uv pip install nexus-admin`.

### Phase 6: Benchmarks, Hardening & Security Audits (Week 15)
- [ ] Run automated security penetration tests:
  - CSRF header omissions
  - SQL injection via query parameters and sort columns
  - Mass assignment override attacks
  - Tenant boundary bypasses in `get_queryset`
- [ ] Run benchmark comparison tests against `sqladmin`:
  - Measure p50/p95/p99 latency
  - Measure peak memory allocation per worker under concurrent workloads (Locust/k6)
  - Profile DOM node counts and UI rendering metrics (Lighthouse CI)

### Phase 7: Documentation, Examples & Public Launch (Week 16)
- [ ] Build documentation using MkDocs Material:
  - "Quick Start in 5 Minutes"
  - Advanced Multi-Tenancy Scenarios
  - Custom Widget Development Guide
  - Migration Guide from `sqladmin` / Django Admin
- [ ] Provide three reference implementations:
  - Minimal Single-File App
  - SaaS Multi-Tenant Architecture
  - High-Volume E-Commerce Platform
- [ ] Tag `0.1.0-beta` release and distribute to PyPI.

---

## 8. Verification & Performance Validation Suite

### 8.1 Automated Performance Tests
Every CI workflow runs benchmark gates comparing against regressions:
```bash
# Execute integration test battery against spun-up PostgreSQL container
uv run pytest tests/integration -v --asyncio-mode=auto

# Assert memory and query counts on list endpoints
uv run pytest tests/benchmarks/test_nplusone_prevention.py
```

### 8.2 Assertion Criteria
1. **Query Count Invariance:** A list view displaying 50 items with 3 related foreign keys must execute in exactly **2 queries** (1 for base records, 1 batch load for relationships), regardless of row count.
2. **Deterministic Response Timing:** P95 response times on the 1,000,000-row table list view must remain $< 45 \text{ ms}$ on standard CI container instances.
3. **Zero Client Leakage:** UI memory footprint must remain flat across consecutive virtualized scrolls up to 50,000 loaded nodes.