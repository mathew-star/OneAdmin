# 0019: Permissions. Per-model codenames, grants, overridable hooks

- Status: accepted
- Date: 2026-11-06

## Context
Until M5, every admin user could read every model. Writes make this untenable: support staff need to view orders, but not to delete them. The design review asked for per-model view/add/change/delete plus action permissions, with an override hook.

## Options considered
- **Django-style groups + permissions tables with a UI.** Complete, but a lot of surface for v1, and the UI work belongs to M6+.
- **Roles defined in code** (`AdminSite(roles={...})`). Elegant, but a role change needs a deploy.
- **Direct grants of permission codenames to users, managed by the CLI** (chosen for v1). It is small and auditable; a roles/groups layer can be added on top later without changing codenames or hooks.

## Decision
- **Codenames:**
  - `<slug>.view`, `<slug>.add`, `<slug>.change`, `<slug>.delete`
  - `<slug>.action.<name>` for actions that declare a custom permission
  - `<slug>.*` grants all of one model's permissions
- `AdminIdentity` gains `permissions: frozenset[str]` and `has_perm(codename)`: superusers have every permission.
- **Built-in users:** grants live in `oneadmin_grant(user_id, codename)`, loaded with the session. Manage them with `oneadmin createuser`, `oneadmin grant`, `oneadmin revoke` and `oneadmin perms`.
- **Custom `AuthBackend`s** fill `permissions` themselves, or override the hooks.
- **Hooks on `ModelAdmin`:** `has_view_permission(ctx)`, `has_add_permission(ctx)`, `has_change_permission(ctx, obj=None)`, `has_delete_permission(ctx, obj=None)`.
  - Defaults check the codenames.
  - With `obj` they are called per row, including for every row of a bulk action.
- **Visibility follows permissions:**
  - `/schema` is computed per user. Models without `view` are absent, and each model carries the viewer's `permissions` and allowed `actions`.
  - The ETag is computed per response body.
- **Denied access:** a model you can't view → `404 unknown_model`, which doesn't reveal that it exists. A denied write on a model you *can* view → `403 forbidden`.

## Consequences
- **Breaking for non-superusers:** they now see nothing until granted `<slug>.view`. This is the safe default. `oneadmin check` lists the codenames.
- One extra indexed query per request (grants), in the same transaction as the session lookup.

## Revisit when
Teams ask for groups/roles or a permissions UI.
