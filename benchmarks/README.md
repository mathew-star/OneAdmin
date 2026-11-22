# Benchmarks

The numbers below are from runs I actually did. Every result file records its machine and versions.

## `bench_list.py`: list-page strategy at 1M rows (2026-11-06, local)

- **Setup:** `examples.shop` seeded with 1,000,000 orders (3 tenants, about 333k each) and `ANALYZE`d. PostgreSQL 17.10 (`postgres:17-alpine`, Docker on WSL2), Python 3.13.14, asyncpg, SQLAlchemy 2.1.8. Warm cache, 30 repetitions, one 50-row page, timed end to end in Python.
- **Raw output:** `results-2026-11-06-local.txt`.

| sort | scope | depth | OneAdmin keyset p50 / p95 | OFFSET p50 / p95 |
|---|---|---|---|---|
| `-created_at` | none | 0 | 0.99 / 1.17 ms | 0.78 / 0.91 ms |
| `-created_at` | none | 10k | 1.14 / 1.26 ms | 2.83 / 3.35 ms |
| `-created_at` | none | 100k | 1.07 / 1.34 ms | 20.3 / 21.1 ms |
| `-created_at` | none | 300k | 1.12 / 1.43 ms | 57.9 / 59.4 ms |
| `-shipped_at` (nullable) | none | 300k | 2.56 / 3.23 ms | 34.7 / 42.2 ms |
| `-created_at` | tenant 2 | 300k | 1.15 / 1.62 ms | 66.6 / 70.5 ms |

| count strategy | p50 / p95 |
|---|---|
| exact, unfiltered | 28.2 / 29.1 ms |
| auto (reltuples), unfiltered | 0.54 / 0.69 ms |
| exact, tenant-scoped (~333k rows) | 32.3 / 33.5 ms |
| auto (capped at 10k), tenant-scoped | 4.59 / 5.21 ms |

**Reading:**
- Keyset latency stays flat with depth. OFFSET grows linearly with depth.
- On the first page keyset is about 0.2 ms slower, because of the cursor key columns and page bookkeeping.
- Nullable sorts cost about 1 ms more, because of the two-branch `UNION ALL`.
- Counting dominates OFFSET-style admins: an exact count on every request costs about 28 ms here and grows with table size.

**Caveats:**
- These are warm-cache numbers on a laptop.
- The OFFSET column isolates the strategy competitors use. It does not run their code. A head-to-head against sqladmin and Starlette-Admin is planned for M7.
