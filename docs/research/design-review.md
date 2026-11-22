# Design review: `complete_architecture_implementation_spec.md` ("NexusAdmin")

Reviewer: technical owner. Date: 2026-11-06. Evidence lives in `landscape.md` and `technical-findings.md` (TF§n).

## Summary of the draft (≤200 words)

The draft proposes an async-first admin library for FastAPI and SQLAlchemy 2.0, with a schema-driven React 19 SPA prebuilt into the Python wheel. The backend introspects mapped models once into frozen metadata dataclasses and compiles Pydantic v2 Read, Create and Update models. It exposes a versioned JSON API: schema (ETag), auth, list/detail CRUD, bulk actions and streaming export. Lists select only the displayed columns, use keyset pagination on `(sort, pk)` with an OFFSET fallback, eager-load per `list_select_related`, and use `reltuples` estimates or capped counts. Auth uses DB-backed sessions in HttpOnly cookies, `X-CSRF-Token`, argon2id, and an audit log written atomically in the same transaction, all in an isolated `nexus_admin` schema. Tenancy goes through a `get_queryset` hook. Packaging is hatchling with a build hook that runs `pnpm build`. The frontend uses TanStack Router, Query, Table and Virtual, Tailwind, Radix, cmdk and an Orval client. The roadmap covers 16 weeks part-time and targets PG, MySQL and SQLite. Its performance claims are 2 queries per list, P95 under 45 ms on 1M rows, and flat memory.

## What is sound (kept)
- **The thesis.** A JSON API with a prebuilt SPA, versus server-side Jinja/WTForms, is the right split. FastAdmin and Piccolo show the delivery model works. The competitors' real problems are OFFSET plus exact counts and missing auth/audit (landscape "Gaps"), not SSR as such. **Correction to the thesis:** "event-loop starvation from template rendering" is overstated. Jinja rendering of a 50-row table costs well under 1 ms. The real win is query strategy and interaction latency, and our positioning should say so honestly.
- Selecting columns in lists, keyset pagination, estimated counts, Pydantic-native validation, DB sessions over JWT, an atomic audit log, a Django-like declarative API, and the contract-first approach.

## What is wrong (with evidence)
1. **The keyset predicate is index-hostile.** `a > x OR (a = x AND pk > y)` took 86 ms and read 502k buffers, the same as OFFSET. The bounded or row-value form took 0.6 ms and read 53 buffers (TF§2).
2. **`reltuples` is -1** until the table has been analyzed, and the `relname` lookup is schema-ambiguous (TF§3).
3. **Update model = Optional everything**, which lets a client set NULL on NOT NULL columns. Use "omittable but not nullable" (TF§5).
4. **The OFFSET fallback for nullable sort columns is unnecessary.** Two-phase keyset handles NULLs (TF§2).
5. **The isolated schema is not portable** (SQLite and MySQL), and Alembic with `include_schemas=True` would try to drop it (TF§10).
6. **Python 3.10 floor**: SQLAlchemy 2.1 and Starlette 1.x require 3.11 (TF§1).
7. **The build hook** breaks when building a wheel from the sdist, and it doesn't fail if the assets are missing (TF§8).
8. **"Exactly 2 queries"**: 1 is achievable with joined label columns (TF§4).
9. **The audit snippet** calls `session.commit()` inside a helper. That takes transaction control away from the caller and its hooks. The service layer should own exactly one transaction per request.
10. **`request.state.user`** in the `get_queryset` example tightly couples tenancy to an implicit request attribute. Use an explicit, typed `AdminContext` instead.

## Risky
- **Tenancy only on list queries.** If `get_queryset` isn't applied to detail, update, delete, actions, export, autocomplete and FK-label lookups, you get IDOR. The engine must route **every** read and write through one scoped query builder, and every endpoint gets a security test that tries cross-tenant access (ADR-0006).
- **Bulk actions**: "batch size caps" is not enough. Actions must re-check permission and scope per row, run inside the transaction, and be audited.
- **Export** of 1M rows can exhaust memory or tie up a connection. Use a server-side cursor (`stream()`) with row limits, timeouts and audit.
- **Search** with `ilike '%x%'` on 1M rows is a sequential scan. Document trigram indexes and let `search_fields` plug in a custom search hook. Require a minimum term length.
- **Autocomplete** endpoints are an enumeration and DoS surface. Scope them, rate limit them, and keyset-paginate them.
- **Polymorphic models, association objects, hybrids, custom types**: each needs a defined v1 behavior (TF§4), or someone's bootstrap breaks. Unknown types degrade to read-only and log a warning **at registration** (fail loudly at startup, never at request time).

## Missing
- **Threat model.** Required before any auth work; drafted in `docs/security/threat-model.md`.
- **Permissions model.** The draft has "role" but no semantics. v1 gets per-model view/add/change/delete permissions plus custom action permissions, stored in admin roles, with a `has_*_permission(ctx, obj)` override hook.
- **Optimistic concurrency.** Two admins editing the same row produce silent lost updates. Use a version token (a hash of loaded values, or `version_id_col` if mapped) in an `If-Match` header, and return 409 on conflict.
- **How users plug in their own auth** (SSO, existing user table). Design the `AuthBackend` protocol now even if only the built-in backend ships in v1.
- **Error contract.** A typed problem-details error format for the SPA.
- **Observability.** Structured logs and hooks for timing; no hard dependency on OTel.
- **i18n.** Out of scope for v1, but UI strings are centralized so it can be added later.
- **Upgrade path for the admin tables.** Migrations shipped with the package.
- **Accessibility and design direction.**

## Over-scoped for v1
- **MySQL and SQLite as first-class targets.** v1 is "PostgreSQL first-class, SQLite supported for dev/tests (no estimates, row-value only where supported)". MySQL is best-effort and untested until there is demand. CI cost and dialect edge cases are a big solo-maintainer burden.
- **Redis sessions**: deferred behind a `SessionStore` protocol.
- **Charts and dashboards, the Monaco editor, three reference implementations, Locust/k6 memory comparisons, the migration guide from Django**: all deferred.
- **"Custom widget development guide"**: we can't support third-party JS widgets in a prebuilt bundle without a plugin ABI. That is explicitly a v2 topic (non-goal for v1). The v1 extension points are backend-side (fields, actions, hooks, formatters).

## Creative changes I'm making
1. **Single-query lists via joined label columns**, plus batched to-many lookups.
2. **Count runs in parallel with the page on a second connection, with a statement timeout.** The page never waits on the count.
3. **Plan-shape tests:** CI asserts `EXPLAIN` uses `Index Cond` for keyset pages on Postgres. This catches the exact regression in the draft's snippet, deterministically and without noisy timing gates.
4. **An index advisor at startup:** a warning when `ordering` or `list_filter` columns lack a supporting index. It is cheap, unique among Python admins, and directly addresses "why is my admin slow".
5. **An `AdminContext` object** (user, permissions, tenant, request) passed explicitly to every hook. Hooks receive the active `AsyncSession` (fixes sqladmin #925).
6. **Cursor-in-URL list state.** Every list view is a shareable URL, and the back button works.
7. **`oneadmin check`**, a CLI that validates registrations, reports unsupported types and missing indexes, and dumps the schema contract. It is useful in CI for users too.
