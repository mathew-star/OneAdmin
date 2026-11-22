# Threat model

Status: **finalised for M3** by the technical owner (2026-11-06). Owner review welcome; changes go through an ADR.

Method: STRIDE over the data-flow diagram in PLAN §2.

## Assets
- application data reachable through the admin (often PII and financials)
- admin credentials and sessions
- the audit log (integrity)
- the site secret (cursor signing)
- availability of the host app's DB pool

## Actors
- anonymous internet attacker
- authenticated low-privilege admin
- authenticated admin of tenant A targeting tenant B
- malicious content author (stored XSS via app data)
- compromised dependency

## Threats → controls (✓ = planned control; T = test required)
| # | Threat | Control | Test |
|---|---|---|---|
| S1 | Credential stuffing / brute force | per-user + per-IP DB rate limits, backoff, generic errors, dummy-hash timing | T |
| S2 | Session theft/fixation | opaque hashed tokens, HttpOnly/Secure/SameSite, rotation on login, idle/absolute expiry, revoke on password change | T |
| T1 | CSRF on mutations | synchronizer token header + Origin/Fetch-Metadata + JSON-only | T |
| T2 | Mass assignment (e.g. `is_superuser`, `tenant_id`) | compiled per-admin `WriteSpec` (ADR-0018): any key that isn't writable is an error, never silently dropped; readonly/generated/onupdate/hidden excluded at compile; PKs immutable after create | T ✓ M5 |
| T3 | SQL injection via filter/sort/search/cursor | whitelist against ModelMeta, typed coercion, bound params only, signed cursors | T (fuzz) |
| T4 | Audit tampering | append-only by API (no update/delete endpoints), same-txn writes (a failing audit rolls back the change); DB-level revoke documented | T ✓ M5 |
| R1 | Repudiation | audit entry for every mutation/action/export/login (success + failure) | T |
| I1 | Cross-tenant read/write (IDOR) | single scoped builder (ADR-0006), 404 on out-of-scope; writes: scoped `FOR UPDATE` target lookup, **scope-after-write** re-select (403 `out_of_scope`), FK targets checked through the target's scope | T ✓ M5 (every write endpoint) |
| I2 | Excluded fields leaking (password hashes) | read models derived from allowed fields; `exclude` applies to API, export and audit diffs; secrets redacted in audit | T |
| I3 | Stored XSS via app data rendered in admin | React text rendering only; no `dangerouslySetInnerHTML`; strict CSP (`script-src 'self'`; config as JSON, not inline JS) | T (payload e2e) |
| I4 | User enumeration | uniform login responses/timing | T |
| D1 | Expensive queries (deep OFFSET, huge page size, unindexed search, export) | keyset, page-size cap, count timeout, min search length, export limits + streaming, statement_timeout | T |
| D3 | Memory exhaustion via concurrent password hashing (argon2id = 64 MiB, ~65 ms each, measured) | hashing runs in worker threads behind a per-site `CapacityLimiter` (default 4); excess logins queue; per-IP/per-email rate limits cut volume first | T |
| D2 | Autocomplete abuse | scoped, rate-limited, limited result size | T |
| E1 | Privilege escalation via actions/bulk ops | per-action permission checked per row, scoped `FOR UPDATE` load, all-or-nothing, rows created by the action scope-checked and audited, ≤1,000 rows | T ✓ M5 |
| E2 | Clickjacking | `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` | T |
| E3 | Supply chain | lockfiles, audits in CI, minimal deps, trusted publishing + attestations | CI |

## Out of scope (documented)
- Host-app vulnerabilities.
- DB-level privileges: we recommend a least-privilege DB role.
- Compromised admin endpoint machines.

## M3 design decisions that follow from this model
- **Sessions:** a 256-bit random token goes in the cookie, and **only its SHA-256 is stored**. A leaked database therefore yields no usable sessions.
- **CSRF token** = HMAC(site key, session hash). It is derived rather than stored, so there is nothing extra to leak or keep in sync.
- **Unsafe methods** need:
  - a valid `X-CSRF-Token`, compared in constant time
  - a same-origin `Origin`, or `Sec-Fetch-Site` of `same-origin`/`none`
  - a JSON body
- **The login endpoint has no session**, so it is protected by the Origin/Fetch-Metadata check and the JSON requirement alone (defends against login CSRF).
- **Cookie:** `HttpOnly; Secure; SameSite=Lax; Path=<mount path>`. `Secure` stays on by default even on localhost, since Chrome and Firefox treat `http://localhost` as a secure context. `cookie_secure=False` exists for other dev setups and logs a warning. (Assumption: Safari behavior on localhost is unverified.)
- **Unknown users** are verified against a dummy hash, so response timing doesn't reveal which emails exist. Responses are identical for unknown user, wrong password and inactive user.
- **Rate limiting** is DB-backed, so it works across workers without Redis. The defaults are 5 failures per email or 20 per IP within 15 minutes, answered with 429 and `Retry-After`.
- **Client IP** comes from the ASGI server's `client` value. Configure your server's trusted proxies (uvicorn `--forwarded-allow-ips`); OneAdmin never parses `X-Forwarded-For` itself.
- **A password change revokes all of that user's sessions.** Login always issues a fresh session, which prevents session fixation.

## M5 additions
- **Lost updates (integrity):** HMAC row versions + mandatory `If-Match` on `PATCH`/`DELETE` (`428`/`409`). The token is keyed, so nothing about the row can be learnt or tested offline from it.
- **Least privilege:** staff users start with no permissions (ADR-0019). Models without view permission are indistinguishable from unregistered ones (`404`).
- **Body size:** write bodies are capped at 2 MiB by `Content-Length` (413), and text fields at their column length (or 500k characters).
- **Error disclosure:** constraint violations report the constraint and column names, never the conflicting value (it may belong to a row outside the caller's scope).

