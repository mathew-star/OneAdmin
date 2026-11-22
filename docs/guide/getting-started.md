# Getting started

## Requirements
- Python 3.11+
- FastAPI (or any Starlette app)
- SQLAlchemy 2.0.36+ used with an **async** engine (`create_async_engine`, `async_sessionmaker`)
- PostgreSQL 14+ (fully supported), or SQLite (development)

Apps that use *sync* SQLAlchemy can still use OneAdmin: create a second, async engine for the admin pointing at the same database, using an async driver such as `asyncpg`.

## See it first (1 minute)
```bash
uvx --from 'oneadmin[demo]' oneadmin demo
```

- A shop with a million orders opens in your browser; the login is printed in the terminal.
- It runs in development mode; bind it to your own computer only.
- The data is kept in `~/.cache/oneadmin`; use `--rows 100000` for a smaller one and `--reset` to start over.

## Your own models (5 minutes)

### 1. Install
```bash
uv add oneadmin          # plus "oneadmin[postgres]" or "oneadmin[sqlite]" for the driver
```

Until the first PyPI release, install from a checkout: `uv add --editable path/to/OneAdmin`.

### 2. Write `admin.py` for you
```bash
uv run oneadmin init --models app.models
```

`init` reads your models, finds your `async_sessionmaker` (in `app.database`, `app.db`, ...; or pass `--session app.database:async_session_maker`), and writes `app/admin.py`:

```python
@admin.register(Post)
class PostAdmin(ModelAdmin[Post]):
    list_display = (Post.id, Post.title, Post.author, Post.published, Post.created_at)
    search_fields = (Post.title, "^slug")
    list_filter = (Post.published, Post.created_at)
    ordering = (Post.created_at.desc(),)
```

It's ordinary code you own: edit it freely. If you'd rather not keep a class per model, the same choices are available at runtime with one line:

```python
admin.register_all(Base)            # every model of your declarative base
```

Explicit `@admin.register(...)` classes take precedence over `register_all`, whatever the order.

### 3. Mount it
In your FastAPI app:
```python
from app.admin import admin

admin.mount(app, path="/admin")
```

### 4. Try it locally
```bash
ONEADMIN_DEV=1 uv run uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/admin/`. In **development mode**:
- OneAdmin creates its own tables on the first request.
- The login page offers to create the first admin account. Copy the setup token from the server terminal into the form.
- No secret key is needed.
- The built-in guard checks that the immediate client is loopback. Bind the server to `127.0.0.1` and do not expose it through a reverse proxy.

## Going to production
1. **Secret key:** at least 32 random characters, from the environment:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   ```python
   admin = AdminSite(..., secret_key=os.environ["ONEADMIN_SECRET_KEY"])
   ```
   It signs pagination cursors and derives CSRF tokens.
2. **Point the CLI at your site** in `pyproject.toml`:
   ```toml
   [tool.oneadmin]
   app = "app.admin:admin"
   ```
3. **Keep your Alembic away from OneAdmin's tables** (one line, see [Alembic integration](alembic.md)), then:
   ```bash
   uv run oneadmin migrate
   uv run oneadmin createsuperuser
   uv run oneadmin check        # validates the admin and suggests missing indexes
   ```
4. **Turn development mode off.** Don't set `ONEADMIN_DEV` on servers. A reverse proxy on the same host can make remote requests appear local to the app.

Every option is validated when the app starts. A typo like `list_display = ("titel",)` fails at startup, naming the valid columns, instead of breaking a page later.

## Next
- [`ModelAdmin` reference](model-admin.md): every option and hook
- [Customising OneAdmin](customising.md): field types, conventions, middleware, `oneadmin explain`
- [Multi-tenancy](multi-tenancy.md): `scope_by` in one line
- [Editing, permissions & audit](editing-permissions-audit.md)
