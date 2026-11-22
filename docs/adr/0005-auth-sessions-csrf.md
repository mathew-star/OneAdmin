# 0005: Authentication, sessions and CSRF

- Status: accepted (implemented in M3, 2026-11-06)
- Date: 2026-11-06

## Context
Admin panels are high-value targets. JWTs in localStorage are exposed to XSS. Signed-cookie sessions can't be revoked server-side. The SPA is served from the same origin as the API.

## Decision
- **Opaque server-side sessions.** A random 256-bit token in the cookie; the DB stores only its SHA-256 (`oneadmin_session`).
- Idle timeout (default 30 min) and absolute timeout (default 12 h).
- The token rotates on login and on privilege change. All sessions are revoked on password change.
- **Cookie:** `__Host-` prefix when mounted at `/`, otherwise named `oneadmin_session` with `Path=<prefix>`; `HttpOnly; Secure; SameSite=Lax`.
- **CSRF:**
  - a per-session synchronizer token sent in `X-CSRF-Token`, compared in constant time
  - plus a Fetch-Metadata/Origin check
  - plus JSON-only bodies on unsafe methods
- **Passwords:** argon2id with argon2-cffi defaults; run in a worker thread; rehash on login when parameters change. Unknown users are verified against a dummy hash.
- **Rate limiting:** DB-backed counters per username and per IP, with exponential backoff. A `RateLimiter` protocol allows Redis later.
- Pluggable `AuthBackend` protocol (`authenticate(request) -> AdminIdentity | None`) so apps can bring their own auth (SSO, existing user tables). Built-in backend: `PasswordAuthBackend`.

## Consequences
- One DB lookup per request. A cached session read can come later behind a short TTL.
- Requires HTTPS in production. Dev mode on localhost needs an explicit `insecure_cookies=True`, which logs a warning.

## Revisit when
WebAuthn/passkeys become a v1.x feature (strongly desirable for admin panels).

## Implementation notes (M3)
- The CSRF token is derived (HMAC of the session hash), not stored.
- The Origin check compares host to the `Host` header, so it works behind TLS-terminating proxies.
- Argon2 hashing is capped at 4 concurrent per site (64 MiB each, measured at ~65 ms).
- On success, the rate limit resets the email counter but not the IP counter.
- The cookie is not `__Host-` prefixed, because the admin is usually mounted at a sub-path, which the `__Host-` prefix forbids.
