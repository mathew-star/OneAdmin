# Editing, permissions & the audit log

Built-in create, update and delete go through one write path that enforces validation, scoping, permissions and concurrency, and audits their changes in the same transaction (ADR-0018, ADR-0019). Custom actions execute trusted application code; review their database effects separately.

> Everything here is available in the UI ([Using the admin UI](ui.md#editing)) and through the [HTTP API](api.md#writes).

## What clients can write
A field is writable when it is visible (see `fields` / `exclude`) and none of these apply:

| Not writable | Why |
|---|---|
| listed in `readonly_fields` | your choice |
| identity / computed / auto-increment primary key | the database sets it |
| has `onupdate` / `server_onupdate` (e.g. `updated_at`) | it would be overwritten on every update anyway |
| JSON, array or binary column | not editable in v1 |
| hidden credential-like column (`*password*`, `*token*`, ...) | never exposed |

Other rules:
- **Every key is checked.** Sending a key that isn't writable is an error (`400 validation_failed`), not silently ignored, so a client can't smuggle `is_superuser` or `tenant_id` past you.
- **Updates are partial.** Omitted fields keep their values; `null` is accepted only for nullable columns.
- **Blank text:** required text fields (NOT NULL, no default) refuse `""` and whitespace-only values ("may not be blank"). An empty title or slug is almost always a mistake. List a field in `blank_fields` to allow it.
- **Primary keys** can be set on create when they aren't generated (natural keys), but never changed.
- **Values use the same JSON shapes the API returns**, so a value read from the API can be sent back unchanged:
  - decimals as strings (`"12.50"`): floats are refused because they lose cents
  - datetimes as ISO 8601: tz-aware columns need an offset, naive ones refuse it
  - enums by value or name
  - durations as seconds

## Hooks
```python
from oneadmin import ModelAdmin, ValidationError, action

class OrderAdmin(ModelAdmin):
    readonly_fields = ("created_at",)

    async def clean(self, ctx, data, obj):
        """Cross-field rules. `data` holds only what the client sent, already typed."""
        if data.get("status") == "shipped" and not (data.get("shipped_at") or obj and obj.shipped_at):
            raise ValidationError({"shipped_at": "required when the order is shipped"})
        return data

    async def before_save(self, ctx, obj, *, created):
        obj.updated_by = ctx.identity.email          # server-side values

    async def after_save(self, ctx, obj, *, created):
        ...                                           # runs before commit; raising rolls back

    async def before_delete(self, ctx, obj):
        if obj.status == "paid":
            raise ValidationError("Paid orders can't be deleted.")
```
- Every hook runs **inside the request's transaction**. `ctx.session` sees the change, and an exception anywhere rolls back everything, including the audit entry.
- New rows are created as `Model(**data)`, and updates use `setattr`, so your model's `@validates`, events and column defaults all run.

## Bulk actions
```python
class OrderAdmin(ModelAdmin):
    @action(label="Mark paid", confirm="Mark the selected orders as paid?")
    async def mark_paid(self, ctx, rows):
        for order in rows:
            order.status = OrderStatus.PAID
        return f"{len(rows)} orders marked paid"      # optional message for the user
```
- `POST /models/order/actions/mark_paid` with `{"pks": [...]}` (1 to 1,000 rows).
- The rows are loaded through `get_queryset`, locked (`FOR UPDATE`), checked one by one against the action's permission, and changed in one transaction.
- Changed selected rows and newly added rows of the action's model get audit entries. **All or nothing:** if any selected row is missing, out of scope or not permitted, nothing happens.
- `permission=` takes `"change"` (default), `"delete"`, `"view"`, `"add"`, or `"custom"` for a separately grantable `<model>.action.<name>`. `destructive=True` marks the action as dangerous in the UI.
- `delete_selected` is built in (it needs the delete permission and runs `before_delete` for each row). Turn it off with `bulk_delete = False`.
- Custom actions receive a raw SQLAlchemy session and must be treated as trusted code. OneAdmin checks and audits the selected rows and newly added rows of this model; direct SQL, updates to unselected rows, and changes to other models can bypass those checks and audit coverage. Implement and test authorization and audit for such writes in the action itself.

## Tenancy and scoping on writes
`get_queryset` protects writes as well as reads, from every direction ([multi-tenancy](multi-tenancy.md)):

| Attempt | Result |
|---|---|
| update, delete or act on a row outside your scope | `404`, exactly like a missing row |
| change a row so it leaves your scope (e.g. `tenant_id` → another tenant) | `403 out_of_scope`, rolled back |
| create a row outside your scope | `403 out_of_scope`, rolled back |
| point a foreign key at a row you can't see | `400 validation_failed`: "no Customer with this key" |
| an action that creates rows outside your scope | `403 out_of_scope`, rolled back |

## Concurrency
- A detail read returns `version` (also as `ETag`).
- `PATCH` and `DELETE` require it back as `If-Match`:
  - missing → `428 precondition_required`
  - the row changed since you read it → `409 conflict`, with the current row in `error.current`

  Nobody silently overwrites someone else's edit.
- `version` covers the fields the admin shows. Since updates are partial, a concurrent change to a field you didn't send is preserved either way.

## Permissions
**Codenames:**

| Codename | Allows |
|---|---|
| `<model>.view` | see the model and its rows (`change` also implies view) |
| `<model>.add` | create rows |
| `<model>.change` | update rows and run `permission="change"` actions |
| `<model>.delete` | delete rows and `delete_selected` |
| `<model>.action.<name>` | run an action declared with `permission="custom"` |
| `<model>.*` | all of the above for one model |

**Built-in users:**
```bash
oneadmin createuser --email support@example.com --grant orders.view customers.view
oneadmin grant support@example.com orders.change
oneadmin revoke support@example.com orders.change
oneadmin perms support@example.com
oneadmin check            # lists every model's codenames
```
- Superusers (`createsuperuser`) have every permission.
- Staff users created with `createuser` start with **none**: they see an empty admin until granted.
- Grants take effect on the user's next request.

**Custom rules:** override the hooks, which are called per row where it applies:
```python
class PostAdmin(ModelAdmin):
    async def has_change_permission(self, ctx, obj=None):
        if obj is None:                                 # "may change posts at all?"
            return ctx.identity.has_perm("posts.change")
        return obj.author_email == ctx.identity.email   # only their own posts
```
- Hooks: `has_view_permission(ctx)`, `has_add_permission(ctx)`, `has_change_permission(ctx, obj=None)`, `has_delete_permission(ctx, obj=None)`.
- **What denial looks like:**
  - Without view permission a model doesn't exist for that user: it is absent from `/schema`, and its endpoints answer `404`.
  - A denied write on a visible model answers `403`.
- **Custom `AuthBackend`s** set `AdminIdentity(permissions=frozenset({...}))`, or rely on `is_superuser`.

## The audit log
Built-in create, update and delete, plus tracked custom-action changes, write to `oneadmin_audit_log` in the **same transaction** as the change: if one fails, neither happens. The custom-action limitations above also apply to audit coverage.

| Column | Content |
|---|---|
| `at`, `actor_id`, `actor_email`, `ip` | who and when |
| `action` | `create`, `update`, `delete`, `action:<name>` |
| `model`, `object_pk` | which row (slug and encoded PK) |
| `changes` | `{"field": [old, new]}`; only changed fields for updates |

- Columns hidden from the admin appear by name, with the value `"[hidden]"`. The audit never stores what the admin never shows.
- An update that changes nothing writes no entry.
- Read a row's history with `GET /models/{slug}/rows/{pk}/history` (newest first). It needs view permission on the row.
- OneAdmin never updates or deletes audit rows. Retention (e.g. a periodic `DELETE ... WHERE at < now() - interval '2 years'`) is your decision.
- Changes made outside the admin (your app, SQL) aren't audited here.

## Errors
| Status | `code` | When |
|---|---|---|
| 400 | `validation_failed` | invalid input; every bad field is listed in `error.fields` |
| 403 | `forbidden`, `out_of_scope`, `csrf_failed`, `cross_origin` | permission, scope or CSRF |
| 404 | `not_found`, `unknown_model`, `unknown_action` | missing, outside your scope, or not viewable |
| 409 | `conflict` | stale `If-Match` (`error.current` holds the row) |
| 409 | `integrity_error` | a database constraint (unique, FK, check); `param` names the field when it can be determined |
| 413 | `payload_too_large` | more than 2 MiB of received body bytes, including chunked requests |
| 415 | `unsupported_media_type` | not `application/json` |
| 428 | `precondition_required` | `If-Match` missing |
| 503 | `admin_not_migrated` | run `oneadmin migrate`: writes need the audit table, also with a custom auth backend |
