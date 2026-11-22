# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: SemVer, `0.x` until the API contract is declared stable.

## [Unreleased]
### Added
- A 2 MiB ASGI write-body limit checks actual received bytes, including chunked auth and model requests (ADR-0023).
- Rich Click command help: `oneadmin --help` lists every command, and each command has generated `--help` (ADR-0021).
- Development first-run setup requires a token printed in the server log (ADR-0022).
- Contributor, architecture, SQLAdmin migration, and release-process guides; strict documentation and package-metadata checks in CI.
- The admin UI now shows the visible row range and total in each list footer, preserving the range when paging by cursor. Its data workspace uses compact navigation, a full grid with field type cues, and a restrained graphite and signal-lime palette. Record details, create, and edit screens share the same field grid and navigation; long forms keep save actions visible.
- **Customisation core (ADR-0020).** See [docs/guide/customising.md](docs/guide/customising.md).
  - **Field types** (`oneadmin.fields`): one class per kind of value, owning parsing, validation, filters, sorting, wire format and the UI widget. `EmailField`, `URLField`, `MoneyField(currency)` ship, and custom types are one subclass. `ModelAdmin.field_types`.
  - **Conventions** (`oneadmin.conventions`): `readonly`, `hide`, `field_type`, `label`, `filterable` and `scope_by`, applied site-wide via `AdminSite(conventions=[...])`; `ModelAdmin.ignore_conventions`.
  - **`scope_by`:** tenant isolation in one line, on every read and write; a missing scope value matches no rows; new rows get the column filled in.
  - **Typed options:** `Post.title` and `Post.created_at.desc()` wherever names are accepted; `ModelAdmin[Post]` types the hooks; `ModelAdmin.labels`.
  - **Operation middleware:** `@admin.middleware`.
  - **CLI:** `oneadmin explain MODEL[.FIELD]` (resolved settings with their origin); `oneadmin schema [--diff FILE]`.
  - **UI:** fields render through a widget registry keyed by the schema's `widget`; email, URL and money widgets.
- **Editing UI:**
  - create and edit forms generated from the schema, with a scoped relation picker
  - per-field server errors with a focused summary
  - conflict handling that rebases onto the latest version and keeps the user's edits
  - deletion with confirmation, row selection and bulk actions with confirmation, row history, and toasts
  - controls hidden without permission; editing screens load as separate chunks
- `ModelAdmin.blank_fields`; audit entries carry an `id`.
- **Writes:** `POST`/`PATCH`/`DELETE /models/{slug}/rows` and bulk actions (`POST /models/{slug}/actions/{name}`), with a per-row history endpoint. See [docs/guide/editing-permissions-audit.md](docs/guide/editing-permissions-audit.md).
  - Strict input validation: unknown, read-only, generated and `onupdate` keys are refused; omittable ≠ nullable; every field error is reported at once.
  - One transaction per request: scoped `FOR UPDATE` target lookup, scope-after-write, FK targets checked through the target's scope.
  - Optimistic concurrency: `version` / `If-Match`, `428`/`409`.
  - Hooks: `clean`, `before_save`, `after_save`, `before_delete`; `oneadmin.ValidationError`.
  - `@oneadmin.action(...)` with per-row permission checks, plus the built-in `delete_selected`; `readonly_fields` and `bulk_delete` options.
- **Audit log** (`oneadmin_audit_log`, migration `0002`): one entry per changed row, written in the same transaction, with hidden columns redacted.
- **Permissions:**
  - `<model>.view/add/change/delete`, `<model>.action.<name>` and `<model>.*` codenames
  - `AdminIdentity.permissions` / `has_perm`; `has_add/change/delete_permission` hooks
  - a per-user `/schema` with `permissions` and `actions`
  - CLI: `createuser`, `grant`, `revoke`, `perms`; `check` lists codenames

### Changed
- Custom actions are documented as trusted application code: the author owns scope and audit for unselected rows, other models, and direct SQL (ADR-0024).
- **Breaking (pre-alpha):** `createuser --grant` is repeatable, one codename per option (`--grant orders.view --grant orders.change`).
- Editing drafts survive background row refetches; conflicting saves still use the existing rebase flow.
- Required text fields refuse blank values (`""`, whitespace) unless listed in `blank_fields`. The pilot found an empty post title saved through the admin.
- **Breaking (pre-alpha):** non-superusers now need `<model>.view` (or `.change`) to see a model. Before M5, every admin user could read everything. A model the user can't view now answers `404 unknown_model` instead of `403`.
- **The admin UI (read-only).** It ships prebuilt in the wheel and is served under any mount prefix:
  - sign-in
  - model navigation
  - lists with sortable columns, search, typed filters, cursor paging and cheap counts with "Count exactly"
  - detail pages with linked relations
  - light/dark themes and keyboard/screen-reader support (axe-checked)
  - a strict CSP with no inline code

  See [docs/guide/ui.md](docs/guide/ui.md).
- `scripts/export_openapi.py` and generated TypeScript API types, with staleness checks on both sides.

### Fixed
- Login attempts with malformed email addresses count toward the per-IP rate limit.
- Password changes revoke sessions from a concurrent login by serializing both operations on the user row.
- The built-in login failed on SQLite (`can't compare offset-naive and offset-aware datetimes`). Auth timestamps now use a UTC-aware column type on every backend.
- `/schema` listed relation columns after all plain columns instead of in `list_display` order.
- Default model names: `Category` → "Categories" (was "Categorys"); `OrderLine` → "Order line".
- The build hook could package a stale UI. Built assets are now stamped with a hash of their sources (ADR-0009 amendment).
- **Built-in admin accounts:** `oneadmin_*` tables with packaged migrations; argon2id passwords (off-loop, concurrency-capped); opaque hashed DB sessions with idle and absolute expiry; login rate limiting per email and IP; CSRF (token + origin + JSON-only).
- **`oneadmin` CLI:** `migrate`, `createsuperuser`, `changepassword`, `check` (registration validation, migration status, index advice). The site is found via `--app`, `ONEADMIN_APP` or `[tool.oneadmin]`.
- `oneadmin.alembic.include_object`, which keeps the host app's autogenerate from dropping OneAdmin's tables.
- `AdminSite`, `ModelAdmin` and the read-only `/api/v1`:
  - schema with `contract_version` and ETag
  - list, detail and count endpoints
  - one query per page, with related labels scoped through the target admin
  - concurrent counts
  - JSON-safe value encoding
  - problem-style errors and security headers
- **Query engine:** keyset pagination (row-value or bounded predicates, never the bare OR-expansion), NULL-aware segments, signed sort-bound cursors, whitelisted filters and search, and count strategies.
