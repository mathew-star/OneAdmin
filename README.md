# OneAdmin

**The admin panel for FastAPI + SQLAlchemy 2 that stays fast on tables with millions of rows and is secure before you configure anything.**

> **Status: pre-alpha (0.0.x).** Browsing, editing, bulk actions, permissions and the audit log work end to end (UI and API), with the built-in login and CLI. Release work (M7) comes after the pilot. See [`docs/PLAN.md`](docs/PLAN.md). Don't use it in production yet.

- **Django-style, and then some:**
  - register models in `admin.py`, customise them with `ModelAdmin`, create users with `oneadmin createsuperuser`
  - configure every model at once with site-wide conventions
  - write options as typed attributes (`Post.title`)
  - plug in your own field types and middleware
  - `oneadmin explain` tells you why any setting has its value
- **Fast by construction:**
  - **Keyset pagination** with index-friendly predicates: page 10,000 costs the same as page 1 (about 1.1 ms on 1M rows, [measured](benchmarks/README.md)).
  - **One SQL query per list page**, related-row labels included.
  - **Cheap counts** (estimated or capped) that never block the page.
- **Secure by default:**
  - opaque server-side sessions, hashed at rest
  - CSRF protection and argon2id passwords
  - login rate limiting and strict security headers
  - credential-like columns hidden automatically
- **Multi-tenant safe:** one `get_queryset` hook scopes lists, counts, detail views, the labels of related rows *and every write*. A row can't be edited, moved or pointed at outside your scope.
- **Safe editing:** strict input validation (no mass assignment), optimistic locking with `If-Match`, bulk actions checked per row, and an audit log written in the same transaction as each change.
- **Permissions:** per-model view/add/change/delete and per-action grants, managed with `oneadmin grant`.
- **No Node for users:** the UI ships prebuilt inside the wheel.

Requires Python 3.11+, SQLAlchemy 2.0.36+ (async) and FastAPI. PostgreSQL is fully supported; SQLite works for development.

## Quickstart

```bash
uv add oneadmin            # not on PyPI yet: uv add --editable path/to/OneAdmin
```

**1. Declare the admin** in `app/admin.py`:

```python
from oneadmin import AdminSite, ModelAdmin

from app.config import settings
from app.database import async_session_maker      # your existing async_sessionmaker
from app.models import Post, User

admin = AdminSite(
    title="My App",
    session_factory=async_session_maker,
    secret_key=settings.ONEADMIN_SECRET_KEY,       # >= 32 random characters, from the environment
)

admin.register(User)                                # sensible defaults

@admin.register(Post)
class PostAdmin(ModelAdmin):
    list_display = ("id", "title", "author", "published", "created_at")
    list_filter = ("published",)
    search_fields = ("title", "^slug")
    ordering = ("-created_at",)
```

**2. Mount it** in `app/main.py`:

```python
from app.admin import admin

admin.mount(app, path="/admin")
```

**3. Point the CLI at it** in `pyproject.toml`:

```toml
[tool.oneadmin]
app = "app.admin:admin"
```

**4. Keep your Alembic away from OneAdmin's tables** in `alembic/env.py`. *This step is required*: otherwise your next autogenerate proposes dropping them.

```python
from oneadmin.alembic import include_object

context.configure(..., include_object=include_object)
```

**5. Create the tables and your first admin user:**

```bash
uv run oneadmin migrate
uv run oneadmin createsuperuser
uv run oneadmin check        # validates your admin and suggests missing indexes
```

Then open `http://localhost:8000/admin/` and sign in. See [Using the admin UI](docs/guide/ui.md).

## Documentation

- [User guide](docs/guide/README.md): installation, `ModelAdmin` reference, authentication & CLI, multi-tenancy, Alembic.
- [Design](docs/PLAN.md) and [decisions](docs/DECISIONS.md)
- [Research](docs/research/): competitor landscape, measured findings.
- [Security policy](SECURITY.md) and [threat model](docs/security/threat-model.md)

## Development

```bash
uv sync
uv run pytest                 # needs Docker (PostgreSQL via testcontainers)
uv run ruff check . && uv run mypy
uv build                      # sdist + wheel, bundles the UI
```

The UI lives in [`frontend/`](frontend/README.md) (pnpm).

Contributors: read [`CLAUDE.md`](CLAUDE.md) for the invariants every change must respect.
See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development workflow and release checks.
