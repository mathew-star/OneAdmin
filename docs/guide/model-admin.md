# `ModelAdmin` reference

Subclass `ModelAdmin`, set options as class attributes, and register the class with `@admin.register(Model)`.

- Every option is optional.
- Invalid values raise `ConfigurationError` at startup.

Options that name columns accept strings or mapped attributes (`Post.title`; `ordering` also takes `Post.created_at.desc()`). Site-wide [conventions](customising.md#conventions) apply first, and these options win. `oneadmin explain <model>` shows the result and why.

## List view
| Option | Default | Meaning |
|---|---|---|
| `list_display` | first 8 short columns | Columns **and many-to-one relationship names**. A relationship shows the related row's label (`{"pk": "9", "label": "bob_m"}`), fetched in the *same* SQL query. The primary key is always included. |
| `list_filter` | `()` | Columns clients may filter on. Others are rejected with 400. Operators depend on the type (see [API](api.md#filters)). |
| `search_fields` | `()` | `"name"` contains, `"^name"` starts with, `"=id"` exact; all case-insensitive. Each search word must match at least one field. |
| `ordering` | `("-<pk>",)` | Default sort. The PK is always appended as a tiebreaker, so paging is stable even when many rows share a value. |
| `sortable_fields` | `list_display` columns + `ordering` | Columns clients may sort by. Back each with an index (run `oneadmin check`). |
| `list_per_page` | `50` | 1–500. |
| `count_strategy` | `"auto"` | `auto` uses a planner estimate for big *unfiltered* tables (PostgreSQL) and is otherwise capped at 10,000 ("10,000+"). Also `exact`, `capped`, `estimate`, `none`. Estimates are never used for filtered or scoped lists, so they can't leak other tenants' row counts. |
| `count_concurrently` | `True` | Run the count on a second connection, in parallel with the page. |

## Detail view and visibility
| Option | Default | Meaning |
|---|---|---|
| `fields` | all visible columns | Explicit allow-list. |
| `exclude` | `()` | Columns never sent to clients, in any view. |
| *(automatic)* | | Columns whose names look like credentials (`*password*`, `*secret*`, `*token*`, `*api_key*`, `*_hash`) are hidden unless listed in `fields`. |
| `label_field` | first of name/title/username/email/label/slug/code, else PK | How rows of this model are labelled elsewhere. |

## Field types and labels
| Option | Default | Meaning |
|---|---|---|
| `field_types` | from the SQL type | Per-column field type, e.g. `{Product.price: MoneyField("EUR")}`. See [field types](customising.md#field-types). |
| `labels` | the name in words | Display labels, e.g. `{Post.created_at: "Written"}`. |
| `ignore_conventions` | `()` | Ids of site conventions that don't apply to this admin. |

## Editing
| Option | Default | Meaning |
|---|---|---|
| `readonly_fields` | `()` | Visible columns clients may not write. Generated, `onupdate`, JSON/array/binary columns are always read-only. |
| `blank_fields` | `()` | Required text columns that may be saved as `""` (refused by default). |
| `bulk_delete` | `True` | Offer the built-in `delete_selected` action (needs the delete permission). |

Actions are methods decorated with `@action(...)`. See [Editing, permissions & audit](editing-permissions-audit.md).

## Naming
| Option | Default | Meaning |
|---|---|---|
| `name` | table name | URL slug (`/admin/api/v1/models/<name>/rows`). Set it to register one model twice. |
| `verbose_name` / `verbose_name_plural` | class name in words (`OrderLine` → "Order line") / its regular English plural ("Categories") | Shown in the UI. |

## Hooks
| Hook | Default | Called |
|---|---|---|
| `get_queryset(ctx, stmt)` | unchanged | every read and every write's target lookup and scope check, after any `scope_by` conventions (both run through `apply_scope`, which you don't override) |
| `has_view_permission(ctx)` | `<slug>.view` or `.change` | schema, every endpoint |
| `has_add_permission(ctx)` | `<slug>.add` | create |
| `has_change_permission(ctx, obj=None)` | `<slug>.change` | update (with `obj`), change actions (per row) |
| `has_delete_permission(ctx, obj=None)` | `<slug>.delete` | delete, `delete_selected` (per row) |
| `clean(ctx, data, obj)` | unchanged | create/update, after parsing |
| `before_save(ctx, obj, *, created)` / `after_save(...)` | no-op | around the flush, inside the transaction |
| `before_delete(ctx, obj)` | no-op | delete and `delete_selected` |

```python
class OrderAdmin(ModelAdmin):
    async def get_queryset(self, ctx, stmt):
        """Scope every read and write of this model (and labels pointing here)."""
        return stmt.where(Order.tenant_id == ctx.identity.extra["tenant_id"])
```
`ctx` is an `AdminContext`:
- `identity`: an `AdminIdentity` (`id`, `email`, `is_superuser`, `permissions`, `extra`, and `has_perm(codename)`)
- `session`: the request's `AsyncSession`
- `request`: the Starlette request

See [Editing, permissions & audit](editing-permissions-audit.md) for the write hooks in context.

## Not yet available
Inlines (editing related rows on one page), JSON/array editing, and to-many columns in lists. See `docs/PLAN.md`.
