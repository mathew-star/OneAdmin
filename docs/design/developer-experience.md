# How a developer uses OneAdmin (target DX)

This is the contract we design toward. Every public name here becomes a maintenance promise.

## 1. Install
```bash
uv add oneadmin                       # pilot: uv add --editable ../OneAdmin
```

## 2. Declare the admin (`app/admin.py`, Django-style)
```python
from oneadmin import AdminSite, ModelAdmin
from app.db import async_session_factory      # the app's existing async_sessionmaker
from app.models import Restaurant, Order

admin = AdminSite(
    title="Restaurant SaaS",
    session_factory=async_session_factory,
    secret_key=settings.ONEADMIN_SECRET_KEY,   # >= 32 random bytes; signs cursors, CSRF
)

@admin.register(Restaurant)
class RestaurantAdmin(ModelAdmin):
    list_display = ("id", "name", "city", "is_active", "created_at")
    list_filter = ("is_active", "city")
    search_fields = ("^name", "=id")
    ordering = ("-created_at",)

admin.register(Order)                          # zero-config: sensible defaults from the model
```

## 3. Mount it (`app/main.py`)
```python
from app.admin import admin
admin.mount(app, path="/admin")
```

## 4. Create the admin tables and the first superuser (terminal, like Django)
```bash
oneadmin migrate                 # creates oneadmin_* tables, own Alembic version table
oneadmin createsuperuser         # prompts for email + password (hidden), argon2id-hashed
oneadmin check                   # validates registrations, warns about missing indexes
```
The CLI finds the site the way uvicorn finds an app:
`--app app.admin:admin`, or `ONEADMIN_APP=app.admin:admin`, or once in `pyproject.toml`:
```toml
[tool.oneadmin]
app = "app.admin:admin"
```
It uses the site's own `session_factory`, so it connects to exactly the database the app uses.
Non-interactive form for CI/containers: `oneadmin createsuperuser --email a@b.c --password-stdin`.

## 5. Log in at `/admin`
Email + password → opaque server-side session in an HttpOnly cookie (ADR-0005).

## Why this design
- **Admin users are separate from the app's users.** Like Django's `is_staff`, but stronger: an app-user compromise or a bug in the app's auth doesn't hand out admin access, and the admin works on day one without the app having any auth at all.
- **Our tables never touch the app's migrations.** Prefixed `oneadmin_*`, separate Alembic version table, and a helper so the app's autogenerate ignores them (ADR-0012, measured in technical-findings §10).
- **Nothing happens implicitly at startup.** No auto-created tables, no default password. `migrate` and `createsuperuser` are explicit, as in Django. If the tables are missing, `/admin` shows a clear "run `oneadmin migrate`" message instead of a stack trace.
- **Escape hatch, not default:** apps that want SSO or their own users later plug in an `AuthBackend` (`async def authenticate(request) -> AdminIdentity | None`). Same permission model either way.

## Permissions (v1)
- `is_superuser`: everything.
- Other admin users: per-model `view` / `add` / `change` / `delete` grants, plus `ModelAdmin.has_*_permission(ctx, obj)` overrides for row-level rules and tenant scoping via `get_queryset(ctx, stmt)`.
