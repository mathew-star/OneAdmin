# M3: Built-in admin users, login, CLI

ADR-0016, threat model in `docs/security/threat-model.md`.

## Tasks
- `oneadmin/auth/tables.py`: SQLAlchemy **Core** tables on their own `MetaData`: `oneadmin_user`, `oneadmin_session`, `oneadmin_login_attempt`. Core rather than ORM, so nothing joins the user's mapper registries.
- `oneadmin/auth/migrations/`: packaged Alembic environment, version table `oneadmin_alembic_version`, hand-written `0001`.
- `oneadmin/auth/passwords.py`: argon2id in worker threads behind a `CapacityLimiter`; rehash on login; dummy-hash verification; password policy.
- `oneadmin/auth/sessions.py`, `ratelimit.py`, `users.py`, `backend.py` (`PasswordAuthBackend`).
- `oneadmin/api/auth_routes.py`: `POST /auth/login`, `POST /auth/logout`, `GET /auth/session`; CSRF + Origin guard on unsafe methods.
- `oneadmin/cli`: `migrate`, `createsuperuser`, `changepassword`, `check` (including an index advisor). App discovery via `--app`, `ONEADMIN_APP` or `[tool.oneadmin]`.
- `oneadmin/alembic.py`: `include_object` so the host app's autogenerate ignores our tables.
- `AdminSite`: the built-in backend becomes the default; missing tables give a 503 `admin_not_migrated` that says to run `oneadmin migrate`.
- Switch `backend/` from `LocalDevAuth` to the built-in login.

## Acceptance
- Migration test: upgrade → `compare_metadata` reports no diff → downgrade leaves nothing behind.
- Security tests:
  - login timing/shape is uniform
  - rate limit returns 429 with `Retry-After`
  - session fixation (the session changes on login)
  - logout and password change revoke sessions
  - expired and idle sessions are rejected
  - CSRF is missing/wrong, or comes from a cross-site origin
  - non-JSON login is rejected
  - cookie flags are correct
  - the token is never stored in plaintext
- CLI tests: createsuperuser non-interactive + interactive (stdin), duplicate email, weak password, migrate idempotent, check output.
- The `backend/` pilot: `oneadmin migrate && oneadmin createsuperuser` works, login works via HTTP, and its autogenerate no longer proposes dropping our tables.
