# 0018: The write path. Validation, scope-after-write, optimistic concurrency, atomic audit

- Status: accepted
- Date: 2026-11-06

## Context
Admin writes are where admin panels lose data and leak tenants:
- **Mass assignment:** clients set columns they shouldn't (`is_superuser`, `tenant_id`, a PK).
- **"Omittable" confused with "nullable":** a PATCH that omits a field must leave it alone; an explicit `null` must be rejected for NOT NULL columns.
- **Cross-tenant writes:**
  - updating a row outside the scope (IDOR)
  - *moving* a visible row out of the scope
  - creating a row in another tenant
  - pointing a foreign key at another tenant's row
- **Lost updates:** two admins edit the same row; the last save silently wins.
- **Audit trails that lie:** an audit row committed separately from the change survives a rollback, or the change survives a failed audit insert.

## Options considered
- **Generated Pydantic models per admin for input validation.** Pydantic's coercion rules (lax `"5"` → 5, its own `Decimal`/`datetime` parsing) would differ subtly from our wire format on the read path (decimals as strings, integers beyond 2^53 as strings, the tz-aware/naive rules of filters). Two coercion layers that must agree is a bug farm.
- **A compiled per-admin write spec with explicit per-kind parsers** (chosen). It is the same parsing as filters and wire output, collects *all* field errors at once, and still rejects unknown fields. The API layer keeps Pydantic for the request envelope.
- **Concurrency token via `version_id_col` only:** needs every user's model to opt in. A token derived from the row works everywhere.

## Decision
1. **Input:**
   - Each admin compiles a `WriteSpec` with the writable fields: visible, not `readonly_fields`, not generated (identity/computed/autoincrement PK), not binary/JSON/array in v1.
   - Validation rules:
     - Unknown, read-only, generated and `onupdate` keys are rejected with `400 validation_failed`, listing every bad field in `fields`.
     - On create: a missing required field (NOT NULL, no default) is an error.
     - On update: omitting a field leaves it unchanged; `null` is accepted only for nullable columns.
     - Strings are checked against `max_length`; decimals against `NUMERIC(p,s)`; enums against their members.
   - `ModelAdmin.clean(ctx, data, obj)` is the hook for cross-field rules; it raises `oneadmin.ValidationError({field: message})`.
2. **One transaction per request**, owned by the write service. It commits once at the end and rolls back on any error, including errors from the hooks.
3. **Scoped target lookup:**
   - update, delete and action targets are loaded with `get_queryset(ctx, select(Model)).where(pk) FOR UPDATE OF <model>`
   - not found → `404` (existence never revealed)
4. **Scope after write:**
   - After flushing a create or update, the row is re-selected *through `get_queryset`*. If it is no longer visible, the request fails with `403 out_of_scope` and everything rolls back.
   - Foreign keys written to a registered target are checked through the *target's* `get_queryset` (`400 validation_failed: no <Target> with this key`). The check is driven by the column's `ForeignKey` metadata, so FK columns without an ORM `relationship()` are covered too.
   - Rows an action *creates* (new instances of the model in the session) get the same scope check and audit.
   - Together these make "you can only write what you can see, and only make it point at what you can see" a property of the engine, not of each app's hooks.
5. **Optimistic concurrency:**
   - The detail response carries `version` = `HMAC(site key, slug + canonical JSON of the row's *visible* field values)`, truncated to 128 bits.
   - **Implementation note:** the first draft hashed *all* mapped columns, hidden ones included. The final design covers what the user saw, which is the right meaning of "you edited a stale view". Since a PATCH only sends the fields it changes, a concurrent change to a field the editor didn't touch is never overwritten anyway. It stays keyed so tokens are opaque.
   - `PATCH`/`DELETE` require `If-Match: <version>`: missing → `428 precondition_required`; stale → `409 conflict`, with the current row in the body.
6. **Audit (same transaction):**
   - Every create, update, delete and action row writes one `oneadmin_audit_log` entry: actor id/email, action, model slug, encoded PK, IP, time, and changes `{field: [old, new]}`.
   - Columns hidden from the admin are recorded by name with values redacted.
   - If the audit insert fails, the change rolls back; if the change fails, there is no audit row.
   - There is no API to modify or delete audit entries.
7. **Database constraint errors** (unique, FK, check) become `409 integrity_error` with the constraint name and no SQL. The transaction is rolled back.

## Consequences
- Writes go through the ORM unit of work (`setattr` on a loaded instance), so the app's `@validates`, events and `onupdate` defaults run as usual. This costs one scoped `SELECT ... FOR UPDATE`, the write, and one scoped re-select per row.
- Unsupported column kinds (JSON, arrays, binary) are read-only in v1.
- Writes require OneAdmin's tables (for the audit log), also for sites with a custom `AuthBackend`.

## Revisit when
- Users need JSON/array editing: add parsers with size limits.
- Bulk actions on more than 1,000 rows are needed: use background jobs and a queued audit.
