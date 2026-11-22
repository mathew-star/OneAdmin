# M1: Query engine

## Goal
Prove the riskiest, most differentiating part: a list-query engine that stays fast at any table size and page depth, and is safe against hostile input. It lives in `oneadmin.core` with no web dependencies.

## Scope
- `core/meta.py`: column introspection into frozen `FieldMeta` / `ModelMeta`:
  - kinds, nullability, PK (composite), enums, tz-awareness
  - computed/identity/server defaults
  - TypeDecorator unwrapping
  - unknown types degrade to non-sortable
- `core/coerce.py`: strict typed parsing of client strings (filters) and of cursor values.
- `core/query/sorting.py`:
  - parse `-created_at,name` against an allow-list
  - complete with the PK; **the PK tiebreaker inherits the last key's direction**, so the common case stays uniform and row-value-eligible
  - explicit NULLS placement only on nullable keys (PG semantics: ASC → NULLS LAST)
- `core/query/cursor.py`: HMAC-signed, size-limited, sort-bound cursors.
- `core/query/keyset.py`: predicate compiler.
  - Uniform, non-null keys → row-value form (PG, SQLite); otherwise the bounded nested form.
  - Nullable leading key → two segments combined with `UNION ALL` of individually limited, index-friendly branches.
  - Expression sort or nullable non-leading key → offset mode.
- `core/query/filters.py`: `f.<field>[__op]=value` with a per-kind op allow-list; LIKE autoescape; limits on clause count and `in` size.
- `core/query/search.py`: Django-style `search_fields` (`^` prefix, `=` exact, default icontains); AND of terms, OR of fields; limits on terms and length.
- `core/query/counting.py`: exact / capped / estimate / auto / none.
  - The estimate is used only when the statement has **no WHERE at all**. Otherwise a tenant's admin could learn the global row count.
  - On PG, a statement timeout returns "unknown".
- `core/query/paginate.py`: `fetch_page()` ties it together.

## Out of scope (M2)
- Relationship label joins, to-many batched columns, `ModelAdmin`, HTTP.

## Acceptance criteria
- Unit tests for parsing, coercion, cursor tamper/size/sort-mismatch, filter op allow-lists and injection-ish payloads (SQL metacharacters, unicode, `%`/`_` wildcards).
- PG integration tests, on a seeded 1M-row `order` table:
  - **Exhaustive walk equivalence:** paging forward and backward through every page yields exactly `ORDER BY ... ` over all rows (no dupes, no gaps). Covers: duplicate sort values, nullable sort both directions, mixed directions, composite PK, empty results, a single page, a filter plus a sort.
  - **Plan shape:** `EXPLAIN` of a deep keyset page has an `Index Cond` on the leading key for asc, desc, nullable (both segments), tenant-scoped, and row-value forms.
  - **Query count:** one statement per page.
  - Counts: `reltuples` guard (−1 → fallback), capped, estimate refused when filtered, timeout → unknown.
- `docs/research/experiments/bench_list.py` records p50/p95 at 1M rows (keyset vs OFFSET, deep pages) on this machine.
