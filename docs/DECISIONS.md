# Decisions index

| ADR | Title | Status | One-line summary |
|---|---|---|---|
| [0001](adr/0001-json-api-plus-prebuilt-spa.md) | JSON API + prebuilt SPA | accepted | Versioned JSON API; React SPA compiled into the wheel; no Node for users |
| [0002](adr/0002-scope-sqlalchemy-async-postgres-first.md) | Scope | accepted | SQLAlchemy async only; PG tier-1, SQLite tier-2, MySQL best-effort |
| [0003](adr/0003-keyset-pagination.md) | Keyset pagination | accepted | Bounded nested predicate (not the draft's OR form), two-phase NULLs, signed cursors |
| [0004](adr/0004-count-strategy.md) | Counts | accepted | reltuples (guarded) / capped / exact on demand; concurrent with timeout |
| [0005](adr/0005-auth-sessions-csrf.md) | Auth & sessions | accepted | Opaque DB sessions (hashed), synchronizer CSRF + Origin, argon2id off-loop |
| [0006](adr/0006-scoped-queries-admin-context.md) | Scoping & AdminContext | accepted | Every read/write goes through one scoped builder; explicit context in all hooks |
| [0007](adr/0007-supported-versions.md) | Supported versions | proposed (owner) | Python 3.11–3.14; SQLAlchemy 2.0.40–2.1.x; PG 14–18 |
| [0008](adr/0008-schema-contract.md) | Schema contract | accepted | Pydantic is source of truth; contract_version; openapi-typescript; snapshot tests |
| [0009](adr/0009-packaging.md) | Packaging | accepted | Hatch hook builds SPA; prebuilt assets shipped in sdist; fail loud if missing |
| [0010](adr/0010-testing-stack.md) | Testing | accepted | pytest + testcontainers PG17, plan-shape & query-count tests, Vitest, Playwright |
| [0011](adr/0011-frontend-stack.md) | Frontend stack | accepted | React 19/Vite 8/TanStack Router+Query/Radix/Tailwind 4; no TanStack Table in v1 |
| [0012](adr/0012-admin-tables-and-migrations.md) | Admin tables | accepted | `oneadmin_` prefix, own Alembic env + version table, include_object helper |
| [0013](adr/0013-license.md) | License | proposed (owner) | Recommend MIT |
| [0014](adr/0014-project-name.md) | Name | accepted | `oneadmin` (distribution, import and CLI) |
| [0015](adr/0015-pilot-integration-first.md) | Pilot first | accepted | Plug into the owner's FastAPI project before any release work; milestones re-ordered |
| [0016](adr/0016-builtin-admin-users-and-cli.md) | Built-in admin users + CLI | accepted | Django-style `migrate` / `createsuperuser`; built-in users & sessions before the pilot; `AuthBackend` as escape hatch |
| [0017](adr/0017-sqlalchemy-first-adapter-ready.md) | SQLAlchemy-first, adapter-ready | accepted | One backend in v1; API/UI see only ORM-neutral results; adapters later on demand |
| [0018](adr/0018-write-path.md) | Write path | accepted | Compiled write spec (extra keys rejected, omittable ≠ nullable); scoped FOR UPDATE; scope-after-write; HMAC row versions + If-Match; same-transaction audit |
| [0019](adr/0019-permissions.md) | Permissions | accepted | `<slug>.view/add/change/delete/action.<name>` codenames; CLI-managed grants; overridable `has_*_permission` hooks; per-user schema |
| [0020](adr/0020-extensibility-architecture.md) | Extensibility architecture | accepted | `FieldType` per kind of value; compiler with provenance; site conventions; one `apply_scope`; typed options; operation middleware; `schema --diff` |
