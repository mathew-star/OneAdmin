# Open questions, assumptions, limitations

## Needs owner decision
- [x] **Pilot project**: `9x/restaurntsaas-backend`, on a separate branch (ADR-0015).
- [x] **Pilot auth**: built-in admin users via `oneadmin createsuperuser` (ADR-0016).
- [x] **Name** (ADR-0014): `oneadmin`, decided.
- [ ] **License** (ADR-0013): MIT recommended.
- [ ] **Python floor** (ADR-0007): 3.11+, which drops the draft's 3.10.
- [ ] **Scope cuts** (PLAN §1 non-goals): MySQL best-effort, no JS plugins, no dashboards/i18n/SSO in v1.

## Assumptions to verify (owner: me)
- [x] `uv build` builds the wheel from the sdist, and our hook handles it. Verified in M0, including with pnpm removed from PATH.
- [ ] Starlette `mount` + `root_path` works with `<base href>` injection under a nested prefix and behind a proxy with `--root-path` (M5).
- [x] argon2id default cost: ~65-70 ms per hash on this machine (64 MiB). Off-loop with a concurrency cap of 4.
- [ ] PG plan shape is stable for the bounded keyset form on PG 14–18. Verified locally on 17 only; CI covers 14 and 18 but hasn't run yet because there is no remote.
- [~] SQLAlchemy 2.0 vs 2.1 typing. **Partly resolved in M1:**
  - 2.1's variadic `Select` means `Select[Any]` is a one-column select, so the library uses `oneadmin.core._typing.AnySelect` (`Select[Unpack[tuple[Any, ...]]]`).
  - Runtime tests pass on 2.0.57 and 2.1.8.
  - mypy on *our* source passes only against 2.1. Under 2.0 it reports `Unpack is only valid in a variadic position` in `_typing.py`; users don't see this because mypy doesn't report errors inside installed packages.
  - Open: verify how a 2.0 user's call sites type-check against our signatures (M2).
- [ ] Joined/single-table inheritance introspection behavior (M1 fixture zoo).
- [ ] PyPI trusted publishing details re-checked against current docs at release time (M7).
- [ ] Gzip/brotli precompressed asset serving (M5).

## Known limitations (by design, v1)
- Keyset lists have no "jump to page N".
- Nullable *non-leading* sort keys fall back to OFFSET.
- Sorting by hybrid/expression columns uses OFFSET.
- No estimated counts on SQLite/MySQL.
- Offset-mode lists (nullable non-leading key) have no "last page".
- A forward page fetched after its boundary rows were deleted can come back empty with no `prev_cursor`. The UI must offer "back to first page".
- Search uses `ILIKE '%term%'`, which needs `pg_trgm` GIN indexes to be fast on large tables. `oneadmin check` should advise on this (M2).
- [ ] SQLModel models: should work (they're SQLAlchemy mapped classes); add a test fixture.
- [ ] Sync-SQLAlchemy apps: document the second async engine for the admin.
- [ ] **Bundle headroom:** initial JS is 143 KB of the 150 KB budget after M6 (React DOM and TanStack Router dominate). The editing screens are lazy chunks; the detail page, history, dialogs and the action bar are not.
- [ ] **Command palette (`cmdk`) deferred from M6:** it would have to be lazily loaded to fit the budget. Revisit with pilot feedback: is it wanted?
- [ ] TypeScript is pinned to 6.0: TypeScript 7 (the native port) has no JS API, which openapi-typescript needs. Revisit when openapi-typescript supports TS 7.
- [ ] The UI logs one browser-level `401` on the signed-out session probe (`GET /auth/session`). It's harmless, but noisy in the console; a `200 {user: null}` would avoid it at the cost of a contract change.
- [ ] **Built-in users have no tenant attributes** (`AdminIdentity.extra` is empty). Multi-tenant back offices with per-tenant staff need a custom `AuthBackend`. Option: an `extra` JSON column on `oneadmin_user` with a CLI flag. Decide with pilot feedback.
- [ ] **Actions that write to *other* models** are not audited or scope-checked by OneAdmin (documented). Consider tracking every dirty/new instance in the session.
- [ ] **Login events are not in the audit log** (threat model R1 lists them). They live in `oneadmin_login_attempt` for 24 h only.
- [ ] **JSON/array columns are read-only** in v1 (ADR-0018).
- [ ] Contract snapshot test for `/schema` (planned in M2, not yet written; the schema shape is asserted field-by-field in test_api_pg instead).
- [ ] Safari and `Secure` cookies on `http://localhost`: unverified (Chrome and Firefox accept them).
- [x] Non-superuser admin users could read every model. Fixed in M5 (ADR-0019): grants are required.
- [ ] The login rate limit's check-then-insert isn't atomic: concurrent attempts can overshoot by the number in flight.
- [ ] `oneadmin check` index advice reads model metadata only; it can't see indexes created only in migrations.
