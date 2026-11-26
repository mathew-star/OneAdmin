# Authentication & the `oneadmin` CLI

## Admin users are separate from your app's users
OneAdmin keeps its own accounts in `oneadmin_user`, much like Django's staff users. This means:
- the admin works even in an app with no login of its own
- a bug in your app's auth can't grant admin access

## Commands
Run `oneadmin --help` to see every command, or `oneadmin COMMAND --help` for its options. Help is formatted with Rich Click.

```bash
oneadmin migrate                      # create/upgrade OneAdmin's tables (idempotent)
oneadmin migrate --downgrade base     # remove OneAdmin's tables entirely
oneadmin createsuperuser              # prompts for email and password; every permission
oneadmin createuser [--grant CODE]... # repeat --grant for each permission
oneadmin grant EMAIL CODE...          # e.g. orders.view orders.change
oneadmin revoke EMAIL CODE...
oneadmin perms EMAIL                  # show what a user may do
oneadmin changepassword EMAIL         # also signs that user out everywhere
oneadmin check                        # validate registrations, list codenames, migrations, index advice
oneadmin explain MODEL[.FIELD]        # the resolved configuration, and why
oneadmin schema [--diff FILE]         # configuration as JSON, or what changed since FILE
oneadmin init --models app.models      # generate a starting admin.py
oneadmin demo                          # start a local seeded shop
oneadmin convert sqladmin FILE         # convert sqladmin ModelView declarations
```

For scripts and containers, there are non-interactive forms:
```bash
echo "$ADMIN_PASSWORD" | oneadmin createsuperuser --email ops@example.com --password-stdin
```

### Finding your site
In order of precedence:
1. `--app app.admin:admin`
2. the `ONEADMIN_APP` environment variable
3. `[tool.oneadmin] app = "..."` in the nearest `pyproject.toml`

Run the CLI inside your project's environment (`uv run oneadmin ...`). It connects with your site's own engine.

## Passwords
- At least 12 characters, at most 1024, and not part of the email address. There are no composition rules (NIST SP 800-63B).
- Stored as argon2id with argon2-cffi's defaults. Hashing runs off the event loop, with at most 4 at a time per site, because each hash uses 64 MiB of memory.

## Sessions
- Login sets the cookie `oneadmin_session`: `HttpOnly; Secure; SameSite=Lax; Path=<mount path>`.
- The database stores only a SHA-256 of the token.
- Defaults: 2 hours idle, 12 hours absolute. Change them with `AdminSite(auth_settings=AuthSettings(...))`.
- **HTTPS:** cookies are `Secure` by default. Browsers treat `http://localhost` as secure, so local development works. `cookie_secure=False` is available for other plain-HTTP dev hosts and logs a warning.

## CSRF
Every state-changing request needs:
- a JSON body
- a same-origin `Origin` header (compared by host, so TLS-terminating proxies work), or `Sec-Fetch-Site: same-origin`
- when authenticated, the `X-CSRF-Token` header from `POST /auth/login` or `GET /auth/session`

Add other hosts to the CSRF allowlist with `AdminSite(trusted_origins=["https://admin.example.com"])`. For a separate-host UI, the host app must also configure credentialed CORS and cookies suitable for that deployment; the bundled UI uses same-origin requests. If a reverse proxy rewrites `Host`, add the browser-facing origin here or preserve the original `Host` in the proxy.

## Rate limiting
- Defaults: 5 failed logins per email or 20 per client IP within 15 minutes. The response is `429` with `Retry-After`.
- A successful login resets the email's counter but not the IP's.
- The client IP comes from your ASGI server. Behind a proxy, configure the server's trusted proxies (uvicorn `--forwarded-allow-ips`). OneAdmin never reads `X-Forwarded-For` itself.

## First-run development setup
With `ONEADMIN_DEV=1`, the server prints a random first-run setup token at startup. Enter it on the setup form when creating the first admin. The token is never returned by the API. Keep the server bound to a loopback address; the loopback check sees the immediate peer, which may be a reverse proxy.

## Bringing your own auth
Pass any object with `async def authenticate(self, request) -> AdminIdentity | None` as `AdminSite(auth_backend=...)`. The built-in login routes are then disabled.

Your backend decides what each identity may do: set `AdminIdentity(permissions=frozenset({"orders.view", ...}))`, or `is_superuser=True`. See [permissions](editing-permissions-audit.md#permissions).
