# 0016: Built-in admin users with a Django-style CLI, before the pilot

- Status: accepted (owner preference, 2026-11-06). Amends ADR-0015 (pilot auth) and refines ADR-0005.
- Date: 2026-11-06

## Context
ADR-0015 proposed reusing the host app's login for the pilot. The owner prefers the Django model: admin users created from the terminal (`createsuperuser`). Design and rationale: `docs/design/developer-experience.md`.

## Options considered
1. Reuse host-app auth via a callback: no new tables, but every app integrates differently, and the admin inherits the app's auth weaknesses.
2. Env-var single password: trivial, but not a real product path.
3. **Built-in admin users + sessions, CLI `migrate` / `createsuperuser` / `check`, with an `AuthBackend` escape hatch.**

## Decision
Option 3, and it ships **before** the pilot so the pilot exercises the real flow.
- CLI discovers the site via `--app module:attr`, `ONEADMIN_APP`, or `[tool.oneadmin] app` in `pyproject.toml`.
- Minimal auth for the pilot: users (email, argon2id hash, is_superuser, is_active), DB sessions (hashed token, idle + absolute expiry), CSRF token + Origin check, login rate limiting, security headers. Roles/per-model grants follow in M5.
- Missing tables produce an actionable error page/API error ("run `oneadmin migrate`"), never a 500.

## Consequences
- The pilot adds `oneadmin_*` tables to the restaurant SaaS dev database. They are isolated by prefix and version table, and `oneadmin` will provide a documented way to drop them (`oneadmin migrate --down base`).
- The threat model (docs/security/threat-model.md) must be approved/finalised as part of this milestone, not after.
