# OneAdmin compared with other admin panels

This is an honest comparison, including where the others are ahead. It reflects sqladmin 0.32, Starlette-Admin 1.0.3, FastAdmin 0.10 and Django admin, as researched on 2026-11-06/07 from their source and issue trackers (`docs/research/landscape.md`).

## Speed on a large table
A 50-row list page of 1,000,000 orders on PostgreSQL, sorted by date. p50 in milliseconds, same machine and data; methodology and raw results in `benchmarks/compare/README.md` in the repository.

| | First page | Middle page | Last page |
|---|---|---|---|
| **OneAdmin** | **4.4** | **4.5** | **4.7** |
| OneAdmin with exact counts | 27.2 | 27.8 | 27.9 |
| sqladmin 0.32 | 112.0 | 141.0 | 170.5 |
| Starlette-Admin 1.0 | 119.4 | 364.8 | 596.1 |

**Why:**
- sqladmin and Starlette-Admin count every row exactly and use `OFFSET`, so pages get slower as the table grows and as you page deeper.
- OneAdmin uses keyset pagination with index-friendly predicates, plus cheap counts with exact counts on demand, so page cost stays flat.
- The others render HTML on the server; OneAdmin returns JSON to a prebuilt UI. See the methodology notes.

## Features

| | OneAdmin | sqladmin | Starlette-Admin | FastAdmin | Django admin |
|---|---|---|---|---|---|
| Async SQLAlchemy 2 | ✓ | ✓ | ✓ | ✓ | (Django ORM) |
| Constant-time deep pages (keyset) | ✓ | ✗ | ✗ | ✗ | ✗ |
| Counts that don't block the page | ✓ | ✗ | ✗ | ✗ | partly (`show_full_result_count`) |
| Built-in users, login, CLI to create them | ✓ | ✗ (bring your own) | ✗ (bring your own) | partly (your user model) | ✓ |
| CSRF protection, rate-limited login | ✓ | ✗ | CSRF ✓ | ? | CSRF ✓ |
| Per-model permissions | ✓ | ✗ | ? | ? | ✓ |
| Tenant scoping on every read *and* write | ✓ (`scope_by`, `get_queryset`) | list only (`list_query`) | list only | ✗ | `get_queryset` (reads) |
| Optimistic locking (no lost edits) | ✓ | ✗ | ? | ? | ✗ |
| Audit log in the same transaction | ✓ | ✗ | ? | ? | `LogEntry` (separate) |
| Site-wide conventions, `explain` | ✓ | ✗ | ✗ | ✗ | ✗ |
| Typed options (`Post.title`) | ✓ | ✓ | partly | ✗ | ✗ |
| Development mode with first-run setup | ✓ | ✗ | ✗ | ✗ | ✗ |
| Inline editing of related rows | ✗ (planned) | ✗ | ✗ | ✓ | ✓ |
| Export (CSV/Excel) | ✗ (planned) | ✓ | ✓ | ✗ | via packages |
| File uploads | ✗ (planned) | ✓ | ✓ | ? | ✓ |
| Translations | ✗ (planned) | ? | ✓ | ? | ✓ |
| Other ORMs | ✗ (by design) | ✗ | ✓ (several) | ✓ (several) | ✗ |
| On PyPI, used in production | ✗ (pre-alpha) | ✓ | ✓ | ✓ | ✓ |

Cells marked **?** weren't verified in the other project's source; corrections are welcome. sqladmin's exact count and `OFFSET` paging, and its lack of a CSRF module, were verified in its 0.32 source; Starlette-Admin's count and paging in its 1.0.3 source.

## When to pick which
- **sqladmin:** small tables, one tenant, trusted admins, and you want a mature, released package today.
- **Starlette-Admin:** you need several ORMs, or translations and export today.
- **Django admin:** you use Django.
- **OneAdmin:**
  - large tables
  - multi-tenant data
  - several people editing the same records
  - an audit trail, or permissions beyond "admin or not"
  - configuring many models at once

  Its gaps (inlines, export, uploads, translations) are on the [roadmap](ROADMAP.md).
