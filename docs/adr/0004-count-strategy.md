# 0004: Count strategies

- Status: accepted
- Date: 2026-11-06

## Context
Exact `count(*)` on every list request is the incumbents' main large-table problem (Starlette-Admin #686). `reltuples` is -1 on tables that have never been analyzed (measured).

## Decision
`ModelAdmin.count_strategy`:
- **`"auto"`** (default):
  - unfiltered on PG: `reltuples` when ≥ `estimate_threshold` (default 100k); otherwise exact
  - filtered: capped at `count_cap` (default 10,000)
- `"exact"` / `"capped"` / `"estimate"` / `"none"`.

The count:
- runs **concurrently** with the page query, on a separate session/connection
- runs with a `statement_timeout` on PG (default 1.5 s); on timeout it returns `{value: null, exact: false}`
- lives in its own endpoint, so the UI can ask for an exact count on demand

`reltuples` is read via `to_regclass(:qualified_name)`.

## Consequences
- An extra pooled connection per list request. Documented, and can be switched off (`count_concurrently=False`).
- The UI must render approximations ("~1.2M", "10,000+").

## Revisit when
Pool pressure shows up in benchmarks.
