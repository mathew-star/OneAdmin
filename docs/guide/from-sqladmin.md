# Coming from SQLAdmin

OneAdmin targets FastAPI applications using async SQLAlchemy. It can generate a starting `ModelAdmin` module from SQLAdmin `ModelView` classes, but the result requires review.

```bash
uv run oneadmin convert sqladmin app/sqladmin.py --output app/admin.py
```

The command reads the source file and writes a new file; it does not edit the input. It translates common options such as `column_list` to `list_display`, `column_searchable_list` to `search_fields`, `column_filters` to `list_filter`, and `page_size` to `list_per_page`. Unsupported assignments and custom code become `TODO(oneadmin)` comments. Inspect each one before using the generated module.

1. Replace the generated `async_session_maker` import with your application's `async_sessionmaker`. OneAdmin takes a session factory, whereas SQLAdmin commonly takes an engine.
2. Supply a secret key through the environment. Register the generated `admin` on your FastAPI app with `admin.mount(app, path="/admin")`.
3. Follow [Alembic integration](alembic.md), then run `oneadmin migrate`, `oneadmin createsuperuser`, and `oneadmin check`.
4. Review permission hooks, row scoping, custom actions, form fields, and relationships manually. The converter cannot prove that SQLAdmin authorization or custom behavior has an equivalent in OneAdmin.
5. Test create, edit, delete, list filters, and a limited-permission user on your own models before switching traffic.

See [Getting started](getting-started.md), [`ModelAdmin` reference](model-admin.md), and [Editing, permissions & audit](editing-permissions-audit.md) for the destination API. OneAdmin is pre-alpha and is not yet on PyPI; install it from a checkout as the getting-started guide describes.
