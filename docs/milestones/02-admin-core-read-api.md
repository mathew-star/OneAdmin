# M2: Admin core + read API

## Goal
`AdminSite` + `ModelAdmin` registration, mounted into a FastAPI app, serving a versioned read-only JSON API, scoped on every path. Proven against `examples/shop` in tests and against `backend/` (the pilot sample app) by hand.

## Tasks
- `oneadmin/auth/backend.py`: `AdminIdentity`, `AuthBackend` protocol (built-in backend arrives in M3).
- `oneadmin/core/context.py`: `AdminContext`.
- `oneadmin/model_admin.py`: options `list_display` (columns and many-to-one relations), `list_filter`, `search_fields`, `ordering`, `sortable_fields`, `exclude`, `label_field`, `list_per_page`, `count_strategy`; hooks `get_queryset(ctx, stmt)`, `has_view_permission(ctx)`.
- `oneadmin/core/service.py`: list (one page query; FK labels via outer join to the **target admin's scoped** subquery; concurrent count on a second session), detail (scoped `WHERE pk = :pk`).
- `oneadmin/core/wire.py`: JSON-safe values (Decimal→string, ints beyond ±2^53 → string), PK encoding (composite → base64url JSON).
- `oneadmin/api/`: contract models, router, problem errors. `oneadmin/site.py`: `AdminSite.register/mount/build_app`.
- Defaults: sensitive-looking columns (`*password*`, `*secret*`, `*token*`, `*_hash`) excluded unless listed explicitly.

## Acceptance
- Integration tests on PG: list/detail/sort/filter/search/cursor via HTTP; FK labels; one SQL statement per page (count off); cross-tenant detail → 404; FK label of an out-of-scope target is null; unauthenticated → 401; bad params → 400 with code; excluded fields absent from schema and payloads.
- Schema snapshot test. Layering test: `oneadmin.api` does not import `sqlalchemy`.
- Two `AdminSite`s in one process stay isolated.
- The pilot `backend/` app mounts the admin and serves `/admin/api/v1/schema` and rows for users, categories, posts (manual check, recorded in `docs/pilot/`).
