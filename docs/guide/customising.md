# Customising OneAdmin

OneAdmin is configured in Python, resolved once when your app starts, and rendered by the browser. Customisation never costs anything per request, and it can never bypass tenant scoping, permissions, transactions or the audit log.

There are several layers. Use only the ones you need; each builds on the previous.

| Layer | You write | Section |
|---|---|---|
| 1. Options | class attributes on a `ModelAdmin` | [`ModelAdmin` reference](model-admin.md) |
| 2. Typed options | `Post.title` instead of `"title"` | [below](#typed-options) |
| 3. Hooks | methods: `get_queryset`, `clean`, `has_change_permission`, ... | [Editing](editing-permissions-audit.md#hooks) |
| 4. Field types | how a kind of value is parsed, filtered and shown | [below](#field-types) |
| 5. Conventions | rules applied to every model at once | [below](#conventions) |
| 6. Middleware | behaviour around every operation | [below](#middleware) |
| 7. UI widgets | (coming: the frontend plugin SDK) | [ROADMAP](../ROADMAP.md) |

When in doubt, run **`oneadmin explain`**: it shows what was decided and why.

## Typed options
Every option that names a column or relationship also accepts the mapped attribute, and `ordering` accepts `.desc()`:

```python
@admin.register(Post)
class PostAdmin(ModelAdmin[Post]):
    list_display = (Post.id, Post.title, Post.author, Post.created_at)
    list_filter = (Post.published,)
    search_fields = (Post.title, "^slug")       # prefixes still need strings
    ordering = (Post.created_at.desc(),)
    readonly_fields = (Post.slug,)
    labels = {Post.created_at: "Written"}
```

- **Your editor completes names, and renames are safe.** Your type checker sees a removed column, and an attribute of another model is a startup error.
- **`ModelAdmin[Post]` types the hooks:** `obj` in `before_save`, `has_change_permission` and the others is a `Post`. A bare `ModelAdmin` keeps working.

## Field types
A *field type* is everything OneAdmin knows about one kind of value:
- how it is sent to the browser
- how filter text and form input are parsed and validated
- which filter operators it allows
- whether it can be sorted and edited
- which UI widget shows it

Every column gets one from its SQL type. Pick a different one per column:

```python
from oneadmin.fields import EmailField, MoneyField, URLField

class ProductAdmin(ModelAdmin[Product]):
    field_types = {
        Product.price: MoneyField("EUR"),     # "€12.50", exact decimals
        Product.homepage: URLField(),         # validated; shown as a link
        Product.contact: EmailField(),        # validated; shown as mailto:
    }
```

**Built-in types:**

| Kind of type | Types |
|---|---|
| Plain kinds | `StringField`, `TextField`, `IntegerField`, `DecimalField`, `FloatField`, `BooleanField`, `DateTimeField`, `DateField`, `TimeField`, `IntervalField`, `UUIDField`, `EnumField` |
| With validation and a widget | `EmailField`, `URLField`, `MoneyField(currency)` |
| Read-only in v1 | `JSONField`, `ArrayField`, `BinaryField` |

**Your own type is one class.** Subclass the closest built-in and change what differs:

```python
import re
from oneadmin.fields import StringField

SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

class SlugField(StringField):
    def parse_input(self, field, raw):
        value = super().parse_input(field, raw)
        if not SLUG.fullmatch(value):
            raise ValueError("only lowercase letters, digits and single hyphens")
        return value
```

- Filtering, sorting, display and editing are inherited.
- Messages from `ValueError` are shown to the user under the field.
- A type that sets `widget = "..."` is rendered by that widget when the UI knows it, and by its kind otherwise.
- Field types must be immutable: one instance can serve many columns.

## Conventions
Conventions configure every matching field of every model, so 200 models don't need 200 classes:

```python
from oneadmin import AdminSite, conventions as cv
from oneadmin.fields import EmailField

admin = AdminSite(
    ...,
    conventions=[
        cv.readonly(r".*_at", id="timestamps"),          # created_at, updated_at, ...
        cv.hide(r".*_secret"),
        cv.field_type(EmailField(), r"(.*_)?email"),
        cv.label("Created", "created_at"),
        cv.filterable(kind=("boolean", "enum")),
        cv.scope_by("tenant_id", lambda ctx: ctx.identity.extra.get("tenant_id")),
    ],
)
```

**Matching:**
- `name` is a regular expression for the *whole* attribute name.
- You can also match by `kind=`, `models=[...]` or `where=lambda model, field: ...`.
- Criteria combine with AND, and at least one is required.

**Precedence:**
1. the model's defaults
2. conventions, in order (a later one wins)
3. the admin's own options

Things the model itself dictates always win: a database-generated column stays read-only.

**Opting out:** an admin skips a convention with `ignore_conventions = ("timestamps",)`. Give conventions an `id` to make this readable; an unknown id is a startup error.

**`scope_by` and multi-tenancy:** one line scopes every model that has the column, on every read and every write. See [multi-tenancy](multi-tenancy.md#one-line-tenant-isolation).

## Middleware
Middleware runs around every admin operation (list, count, get, history, create, update, delete, action):

```python
from oneadmin.core.operations import Operation, CallNext

@admin.middleware
async def notify_on_delete(op: Operation, call_next: CallNext):
    result = await call_next()
    if op.kind == "delete":
        await slack.post(f"{op.ctx.identity.email} deleted {op.slug} #{op.pk}")
    return result

@admin.middleware
async def maintenance_mode(op: Operation, call_next: CallNext):
    if op.is_write and settings.MAINTENANCE:
        raise PermissionDenied("The admin is read-only during maintenance.")
    return await call_next()
```

- **The core runs inside `call_next()`:** scoping, permissions, validation, the transaction, the audit entry and the commit. Middleware can add behaviour, but not skip those.
- **When `call_next()` returns from a write, the change is committed.** Use `before_save`/`after_save` for work that must be atomic with the change.
- **Order:** the first registered middleware is the outermost.
- **Raising an error stops the operation.** OneAdmin's errors (`PermissionDenied`, `ValidationError`) become the matching HTTP response.
- **`op` carries:**
  - `kind`, `admin`, `ctx`, `slug`, `model`
  - for single rows: `pk`
  - for actions: `pks` and `action`
  - for writes: `payload`
  - for lists: `params`

## Seeing the result: `explain` and `schema`
```console
$ oneadmin explain users.created_at
users.created_at  (users.created_at DATETIME NOT NULL)

  type        DateTimeField()  default (from the column's SQL type)
  shown       yes              default
  label       Created at       default
  writable    no               convention creation-time (src/app/admin.py:28)
  filterable  no
  sortable    yes
```

- `oneadmin explain <model>` gives the overview.
- `oneadmin schema > admin.json` writes the whole configuration as stable JSON.
- Later, `oneadmin schema --diff admin.json` lists exactly what a code change did to the admin, and exits 1 if anything changed. Commit the file and run the diff in CI, so admin changes get reviewed like code.
