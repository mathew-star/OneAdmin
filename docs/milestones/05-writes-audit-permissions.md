# M5: Writes, audit, permissions, actions (backend)

ADR-0018 (write path) and ADR-0019 (permissions). The UI for these is M6.

## Tasks
1. **Migration `0002`:** `oneadmin_grant(user_id, codename)` and `oneadmin_audit_log`.
2. **Permissions:**
   - `AdminIdentity.permissions` / `has_perm`, with grants loaded in `AuthService.resolve`
   - `ModelAdmin.has_{view,add,change,delete}_permission`
   - per-user `/schema`, carrying each model's `permissions` and `actions`
3. **`core/write_spec.py`:**
   - writable fields and per-kind input parsers
   - `validate(payload, creating=...)` collects every field error
   - the `readonly_fields` option
4. **`core/writes.py`, `WriteService`:**
   - `create`, `update`, `delete` and `run_action`
   - one transaction; scoped `FOR UPDATE` lookup; scope-after-write; FK target scope checks
   - HMAC row versions; integrity-error mapping
   - audit rows in the same transaction
5. **Actions:** an `@action(label=..., confirm=..., permission=...)` decorator, plus the built-in `delete_selected`. Each row is checked for permission and audited; at most 1,000 rows per call.
6. **Hooks:** `clean(ctx, data, obj)`, `before_save(ctx, obj, created)`, `after_save(ctx, obj, created)`, `before_delete(ctx, obj)`, and `ValidationError`.
7. **API:**
   - `POST /models/{slug}/rows`
   - `PATCH` / `DELETE /models/{slug}/rows/{pk}`, which require `If-Match`
   - `POST /models/{slug}/actions/{name}`
   - `GET /models/{slug}/rows/{pk}/history`
   - Guards on every write: origin + JSON + CSRF (built-in auth).
   - The detail response carries `version`.
8. **CLI:** `createuser`, `grant`, `revoke`, `perms`; `check` lists the codenames.
9. **Tests:**
   - **Mass assignment:** unknown, read-only, PK and generated fields.
   - **Omittable vs nullable.**
   - **Cross-tenant:**
     - update or delete of a foreign row → 404
     - moving a row out of scope, or creating in a foreign tenant → 403
     - an FK pointing at a foreign row → 400
   - **Concurrency:** 428 and 409.
   - **Audit atomicity:** a failed audit rolls back the change, and vice versa.
   - **Permissions:** a matrix over every endpoint.
   - **CSRF** on every write.
   - **Actions:** per-row checks and the row cap.
   - **Integrity errors** → 409.
10. **Docs:** a "Editing, permissions & audit" guide page, plus CHANGELOG, JOURNAL and the pilot log.

## Acceptance
- Every test above passes on PG, and the core write paths also pass on SQLite.
- In `backend/`, via HTTP:
  - create, update and delete a post as a superuser
  - a staff user with only `posts.view` gets 403 on writes
  - the audit history shows the diffs
