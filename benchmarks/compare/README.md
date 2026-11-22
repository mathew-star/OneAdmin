# Head-to-head: OneAdmin vs sqladmin vs Starlette-Admin

`compare.py` mounts all three admins on one FastAPI app over the same PostgreSQL data (the `oneadmin demo` shop, seeded if needed). It measures a 50-row list page sorted by `created_at` descending, at the first page, the middle (row 500,000) and the last page. Each request runs in-process through `httpx.ASGITransport`, so there is no network.

Before timing anything, it checks that every library returns the *right* first row at each depth.

```bash
uv run --with sqladmin==0.32.0 --with starlette-admin==1.0.3 \
    python benchmarks/compare/compare.py --dsn postgresql+asyncpg://USER:PW@HOST/DB --rows 1000000
```

## Results: 2026-11-07
**Setup:**
- 1,000,000 orders, PostgreSQL 17.10 (Docker on WSL2)
- AMD Ryzen 7 7435HS (16 threads), Python 3.13.14
- 20 requests per cell after one warm-up; p50 / p95 in milliseconds
- raw output: `results-2026-11-07.txt`

| Library | First page | Middle page | Last page |
|---|---|---|---|
| **OneAdmin** (defaults) | **4.4** / 5.1 | **4.5** / 5.3 | **4.7** / 5.3 |
| OneAdmin, exact counts | 27.2 / 29.4 | 27.8 / 28.5 | 27.9 / 28.4 |
| sqladmin 0.32 | 112.0 / 117.8 | 141.0 / 143.7 | 170.5 / 172.7 |
| Starlette-Admin 1.0 | 119.4 / 128.1 | 364.8 / 388.5 | 596.1 / 633.0 |

## What the numbers include, and what they don't
- **Each library as it ships, with its defaults.**
  - sqladmin and Starlette-Admin run an exact `COUNT(*)` and an `OFFSET` query on every page.
  - OneAdmin uses keyset pagination and a capped or estimated count.
  - The "exact counts" row shows OneAdmin paying for an exact count on every page as well. It remains flat with depth, because paging, not counting, is what grows.
- **Output differs.**
  - sqladmin and Starlette-Admin render the HTML page on the server.
  - OneAdmin returns JSON, and its UI, a static bundle, renders it in the browser.
  - The others' numbers therefore include template rendering. OneAdmin's don't include browser rendering, which is client-side and doesn't load the server.
- **OneAdmin's middle page uses a real, signed cursor** at row 500,000, as the UI holds after paging there.
  - OneAdmin has no "jump to page 10,000", by design.
  - The others do, at the cost shown.
- Authentication is off in all three; the network isn't measured.
