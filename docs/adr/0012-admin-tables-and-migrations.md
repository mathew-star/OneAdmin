# 0012: Admin tables and migrations

- Status: accepted
- Date: 2026-11-06

## Context
A dedicated schema is not portable (SQLite, MySQL), and Alembic `include_schemas=True` autogenerate proposes dropping foreign tables (measured, technical-findings §10).

## Decision
- The admin tables use their own `MetaData` and the `oneadmin_` prefix (`oneadmin_user`, `oneadmin_role`, `oneadmin_session`, `oneadmin_audit_log`, `oneadmin_login_attempt`). The PG schema is optional (`AdminSite(db_schema="admin")`).
- Migrations ship inside the package as an Alembic environment with its own version table `oneadmin_alembic_version`. They are applied by `oneadmin migrate` or programmatically (`await admin.migrate()`).
- We provide `oneadmin.alembic.include_object` so the user's autogenerate ignores our tables.

## Consequences
- Users run two migration streams (theirs and ours). Documented in the deployment guide.

## Revisit when
Users ask to fold our migrations into their own Alembic tree. Offer a "copy migrations" command then.
