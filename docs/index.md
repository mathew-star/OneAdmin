# OneAdmin

**The admin panel for FastAPI and SQLAlchemy 2 that's running in five minutes, configurable like Django's, stays fast at millions of rows, and is secure before you configure anything.**

```bash
uvx --from 'oneadmin[demo]' oneadmin demo     # a million-order shop in your browser
```

## Why OneAdmin
- **Fast on big tables.**
  - Keyset pagination with index-friendly predicates: the last page of a million rows costs what the first does (milliseconds).
  - One SQL query per list page, related rows' labels included.
  - Counts never block a page.
- **Five minutes to a working admin.**
  - `oneadmin init` writes a typed `admin.py` from your models, or `admin.register_all(Base)` does it at runtime.
  - Development mode creates the tables and offers to create the first account.
- **Configurable like Django, then some.**
  - `ModelAdmin` options and hooks
  - site-wide conventions for every model at once
  - typed options (`Post.title`)
  - your own field types and middleware
  - `oneadmin explain` says why any setting has its value
- **Multi-tenant safe.**
  - One `scope_by` convention, or one `get_queryset` hook, scopes every read and every write.
  - A row can't be read, edited, moved or pointed at outside the user's scope.
- **Safe editing.**
  - Strict input validation, with no mass assignment.
  - Optimistic locking: two people editing a row never silently overwrite each other.
  - Bulk actions are checked per row.
  - The audit log is written in the same transaction as each change.
- **Secure defaults.**
  - Built-in users with argon2id passwords, hashed server-side sessions.
  - CSRF and origin checks, login rate limiting, per-model permissions, a strict CSP.
- **No Node for you.** The UI ships prebuilt inside the wheel.

## Where to go
- [Getting started](guide/getting-started.md)
- [Customising OneAdmin](guide/customising.md)
- [Compared with other admins](comparison.md)
- [Design decisions](DECISIONS.md) and [roadmap](ROADMAP.md)

!!! warning "Pre-alpha"
    OneAdmin is not on PyPI yet and its API may still change. See the [roadmap](ROADMAP.md).
