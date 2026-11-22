# Multi-tenancy & scoping

`ModelAdmin.get_queryset(ctx, stmt)` is the single place where you restrict what an admin user can see *and change*. OneAdmin applies it to **every** read of that model, and to every write (see [writes](#writes) below):

| Read | Scoped |
|---|---|
| list pages | ✓ |
| counts (including the on-demand exact count) | ✓ |
| detail view | ✓ (out-of-scope rows return 404, exactly like missing rows) |
| labels of *this* model shown on *other* models' rows | ✓ (an out-of-scope label is `null`; the raw FK value is still shown) |

## One-line tenant isolation
For the common case, where every tenant-owned table has a `tenant_id` column, use a site convention instead of a hook on every admin:

```python
from oneadmin import AdminSite, conventions as cv

def tenant_of(ctx):
    if ctx.identity.is_superuser:
        return cv.ALL                         # platform staff see every tenant
    return ctx.identity.extra.get("tenant_id")

admin = AdminSite(..., conventions=[cv.scope_by("tenant_id", tenant_of)])
```

- **Every model with a `tenant_id` attribute is scoped**, on every read and every write, together with that admin's own `get_queryset`.
- **Return values:** the function returns one value, a collection ("any of these tenants"), `cv.ALL` (no restriction), or `None`. **`None` matches no rows.** A user whose tenant is missing sees nothing rather than everything.
- **New rows get `tenant_id` filled in** from a single scope value when the form doesn't send it (`autofill=False` turns this off). Creating or moving a row into another tenant is still refused (`403 out_of_scope`).
- The function may be `async`. It runs once per scoped query, so keep it cheap; read from `ctx.identity`.

## Example: tenant isolation with `get_queryset`
```python
class TenantScoped(ModelAdmin):
    async def get_queryset(self, ctx, stmt):
        tenant_id = ctx.identity.extra.get("tenant_id")
        if tenant_id is None:          # platform staff see everything
            return stmt
        return stmt.where(self.model.tenant_id == tenant_id)

@admin.register(Order)
class OrderAdmin(TenantScoped):
    ...
```

Rules:
- Only add `WHERE` clauses on the model's own columns. `stmt` may already contain joins to related models' labels.
- Index the scope column together with your sort columns, e.g. `(tenant_id, created_at, id)`, so keyset pages stay fast.
- Estimated counts are never used on scoped lists, so they can't reveal a global row count.

## Writes
The same hook guards every write. You can only change what you can see, only leave it where you can still see it, and only point it at rows you can see:
- **Updates, deletes and actions** load their rows through `get_queryset` (`404` otherwise).
- **After every create, update or action**, the rows are re-selected through `get_queryset`. A row that would land outside your scope (another tenant) is refused with `403 out_of_scope`, and the transaction is rolled back.
- **Foreign keys you write** are checked through the *target* model's `get_queryset`.

Details: [Editing, permissions & audit](editing-permissions-audit.md#tenancy-and-scoping-on-writes).

## Where `extra` comes from
`AdminIdentity.extra` is populated by your auth backend. With a custom `auth_backend` you set it yourself. Built-in admin users don't carry tenant attributes yet: they suit single-tenant back offices, or platform staff who see every tenant. For per-tenant admin users, plug in your own `auth_backend`.
