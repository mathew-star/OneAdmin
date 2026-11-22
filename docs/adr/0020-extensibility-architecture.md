# 0020: Extensibility architecture

- Status: accepted
- Date: 2026-11-07
- Context document: `docs/ROADMAP.md` (Phase 1)

## Context
The owner wants Django-level configurability. Django gets there by overriding server-rendered templates; we ship a prebuilt SPA, so that route is closed.

There are also internal problems that grow with every feature:
- The rules for one column kind (display, filter parsing, cursor encoding, write parsing, filter operators, sortability) are spread over `coerce`, `wire`, `write_spec`, `filters`, `meta`, the contract and two frontend modules. Adding a kind means editing all of them.
- Configuration is per `ModelAdmin` only: 200 models need 200 classes to apply one rule.
- Nothing explains *why* a field ended up read-only or hidden.
- Options are strings, so renames silently break the admin until startup.

## Decision
1. **`FieldType`: one class per kind of value.** It owns:
   - wire encoding, query-string parsing (filters, search, PKs), JSON input parsing (writes), cursor encoding
   - filter operators, sortability, writability
   - a UI `widget` key with options

   Built-ins cover every current kind. `EmailField`, `URLField` and `MoneyField` ship as the first non-kind types. The frontend renders by `widget`, falling back to the base `kind`.
2. **The compiler resolves each field into a `ResolvedField`** (type, label, visible, readonly, filterable, sortable). Every value records its **origin**:
   - `default`
   - `convention <name> (file:line)`
   - `ModelAdmin.<option>`
   - `field type rule`

   `oneadmin explain` prints them.
3. **Conventions:** site-wide rules passed to `AdminSite(conventions=[...])`, applied in order between the defaults and the per-admin options:
   - `readonly`, `hide`, `field_type`, `label`, `filterable`
   - `scope_by(column, value)`, which scopes every model that has the column

   Precedence: defaults < conventions < per-admin options. An admin opts out of a named convention with `ignore_conventions`.
4. **One scoping entry point:** every read and write calls `admin.apply_scope(ctx, stmt)`, which applies convention scopes and then the user's `get_queryset`. Invariant 4 is enforced in one function.
5. **Typed options:** every option that names a column also accepts the mapped attribute (`Post.title`), and `ordering` accepts `Post.created_at.desc()`. `ModelAdmin[Post]` types the hooks' `obj`. Attributes of another model are a `ConfigurationError`. Strings keep working.
6. **Operation middleware:** `@site.middleware async def m(op, call_next)` wraps every list/get/count/history/create/update/delete/action.
   - The core (scope, permissions, transaction, audit) runs inside `call_next`, so middleware can add behaviour but can't bypass it.
   - Middleware runs outside the write transaction. Work that must be atomic with the change belongs in `before_save`/`after_save`.
7. **`oneadmin schema [--diff FILE]`:** a stable JSON description of the compiled admin, so configuration changes can be reviewed in pull requests.

## Consequences
- `FieldMeta` gains `type`. `kind` stays the semantic base the UI and API branch on, and becomes a property of the type.
- One more registry per site. There is still no global state: built-in types are immutable, and registries are per site.
- Everything resolves at startup, so the per-request cost is unchanged.
- **Reopened v1 non-goals:**
  - *Frontend plugins:* still deferred to Phase 5, with the widget key as the stable seam.
  - *Dashboards and uploads:* Phases 3–4, as layout blocks and field types.
  - *i18n:* Phase 4.

## Revisit when
A user needs a field behaviour the `FieldType` protocol can't express, or conventions need to match on something other than columns (e.g. relationships).
