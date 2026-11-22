"""Phase-0 verification experiment: keyset pagination + count strategies on PostgreSQL.

Reproduce:
    docker run -d --name oneadmin-research-pg -e POSTGRES_PASSWORD=pg \
        -e POSTGRES_DB=research -p 55432:5432 postgres:17-alpine
    uv run --with 'sqlalchemy[asyncio]>=2.1' --with asyncpg \
        python docs/research/experiments/pg_keyset_and_counts.py

Questions answered (results recorded in docs/research/technical-findings.md):
  Q1. What is pg_class.reltuples before ANALYZE on PG14+? (doc assumes a usable number)
  Q2. Does a row-value comparison (a, id) > (:a, :id) use a composite index range scan?
  Q3. Does the expanded OR form use the index as well? Does the "a >= x AND (...)" form?
  Q4. How do NULLs interact with row-value keyset predicates?
  Q5. Cost of OFFSET deep pages vs keyset on 1M rows (wall-clock, this machine only).
  Q6. Cost of exact count(*) vs capped count vs reltuples vs EXPLAIN estimate.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get("RESEARCH_DSN", "postgresql+asyncpg://postgres:pg@localhost:55432/research")
N = int(os.environ.get("RESEARCH_ROWS", "1000000"))


async def timed(conn, sql: str, params: dict | None = None, repeat: int = 5) -> tuple[float, object]:
    best = float("inf")
    result = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        result = (await conn.execute(text(sql), params or {})).fetchall()
        best = min(best, time.perf_counter() - t0)
    return best * 1000, result


async def plan(conn, sql: str, params: dict | None = None) -> str:
    rows = (await conn.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql), params or {})).scalar_one()
    root = rows[0]["Plan"]

    def walk(node, depth=0):
        bits = [f"{'  ' * depth}{node['Node Type']}"]
        if "Index Name" in node:
            bits.append(f"[{node['Index Name']}]")
        if "Index Cond" in node:
            bits.append(f"cond={node['Index Cond']}")
        if "Filter" in node:
            bits.append(f"filter={node['Filter']}")
        bits.append(f"rows={node.get('Actual Rows')} bufs={node.get('Shared Hit Blocks', 0) + node.get('Shared Read Blocks', 0)}")
        out = [" ".join(bits)]
        for child in node.get("Plans", []):
            out.extend(walk(child, depth + 1))
        return out

    return "\n".join(walk(root)) + f"\n  exec={rows[0]['Execution Time']:.2f}ms"


async def main() -> None:
    engine = create_async_engine(DSN)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS orders"))
        await conn.execute(
            text(
                "CREATE TABLE orders (id bigserial PRIMARY KEY, created_at timestamptz NOT NULL,"
                " shipped_at timestamptz NULL, total numeric(12,2) NOT NULL, status text NOT NULL)"
            )
        )
        # Q1: reltuples on a fresh, never-analyzed, empty table
        r = (await conn.execute(text("SELECT reltuples FROM pg_class WHERE relname='orders'"))).scalar_one()
        print(f"Q1 reltuples fresh empty table: {r}")
        await conn.execute(
            text(
                "INSERT INTO orders (created_at, shipped_at, total, status) "
                "SELECT now() - (g % 100000) * interval '1 minute', "
                " CASE WHEN g % 3 = 0 THEN NULL ELSE now() - (g % 5000) * interval '1 hour' END, "
                " (g % 10000) / 7.0, (ARRAY['new','paid','shipped','cancelled'])[1 + g % 4] "
                f"FROM generate_series(1, {N}) g"
            )
        )
        r = (await conn.execute(text("SELECT reltuples FROM pg_class WHERE relname='orders'"))).scalar_one()
        print(f"Q1 reltuples after bulk insert, before ANALYZE: {r}")
        await conn.execute(text("CREATE INDEX ix_orders_created_id ON orders (created_at, id)"))
        await conn.execute(text("CREATE INDEX ix_orders_shipped_id ON orders (shipped_at, id)"))
    async with engine.connect() as conn:
        await conn.execute(text("COMMIT"))
        await conn.execute(text("ANALYZE orders"))
        r = (await conn.execute(text("SELECT reltuples FROM pg_class WHERE relname='orders'"))).scalar_one()
        print(f"Q1 reltuples after ANALYZE: {r}\n")

        mid = (await conn.execute(text(f"SELECT created_at, id FROM orders ORDER BY created_at, id OFFSET {N // 2} LIMIT 1"))).one()
        p = {"a": mid.created_at, "id": mid.id}

        q_row = "SELECT id, created_at, total FROM orders WHERE (created_at, id) > (:a, :id) ORDER BY created_at, id LIMIT 50"
        q_or = "SELECT id, created_at, total FROM orders WHERE created_at > :a OR (created_at = :a AND id > :id) ORDER BY created_at, id LIMIT 50"
        q_ge = (
            "SELECT id, created_at, total FROM orders WHERE created_at >= :a AND (created_at > :a OR id > :id) "
            "ORDER BY created_at, id LIMIT 50"
        )
        q_off = f"SELECT id, created_at, total FROM orders ORDER BY created_at, id LIMIT 50 OFFSET {N // 2}"
        for name, q in [("Q2 row-value", q_row), ("Q3 expanded OR", q_or), ("Q3 >= AND OR", q_ge), ("Q5 OFFSET N/2", q_off)]:
            ms, rows = await timed(conn, q, p if ":a" in q else None)
            print(f"{name}: best-of-5 {ms:.2f} ms, rows={len(rows)}")
            print(await plan(conn, q, p if ":a" in q else None))
            print()

        # Mixed direction: created_at DESC, id ASC -> row-value comparison is not expressible
        q_mixed = (
            "SELECT id FROM orders WHERE created_at <= :a AND (created_at < :a OR id > :id) "
            "ORDER BY created_at DESC, id ASC LIMIT 50"
        )
        ms, _ = await timed(conn, q_mixed, p)
        print(f"Q3 mixed-direction (DESC, ASC) >=/OR form: {ms:.2f} ms")
        print(await plan(conn, q_mixed, p))
        print()

        # Q4: NULL semantics in row comparison
        r = (await conn.execute(text("SELECT (NULL::int, 1) > (0, 0) AS a, (1, NULL::int) > (0, 0) AS b, (1, NULL::int) > (1, 0) AS c"))).one()
        print(f"Q4 (NULL,1)>(0,0)={r.a}  (1,NULL)>(0,0)={r.b}  (1,NULL)>(1,0)={r.c}")
        # Nullable column keyset, NULLS LAST ascending: two-phase predicate
        mid_n = (await conn.execute(text("SELECT shipped_at, id FROM orders WHERE shipped_at IS NOT NULL ORDER BY shipped_at, id OFFSET 1000 LIMIT 1"))).one()
        q_null = (
            "SELECT id FROM orders WHERE ((shipped_at > :a OR (shipped_at = :a AND id > :id)) OR shipped_at IS NULL) "
            "ORDER BY shipped_at ASC NULLS LAST, id ASC LIMIT 50"
        )
        q_null_split = (
            "SELECT id FROM orders WHERE shipped_at >= :a AND (shipped_at > :a OR id > :id) "
            "ORDER BY shipped_at ASC, id ASC LIMIT 50"
        )
        for name, q in [("Q4 nullable single-predicate", q_null), ("Q4 nullable non-null phase only", q_null_split)]:
            ms, _ = await timed(conn, q, {"a": mid_n.shipped_at, "id": mid_n.id})
            print(f"{name}: {ms:.2f} ms")
            print(await plan(conn, q, {"a": mid_n.shipped_at, "id": mid_n.id}))
            print()

        # Q6: counts
        for name, q in [
            ("exact count(*)", "SELECT count(*) FROM orders"),
            ("exact filtered count", "SELECT count(*) FROM orders WHERE status = 'paid'"),
            ("capped count 10001", "SELECT count(*) FROM (SELECT 1 FROM orders WHERE status = 'paid' LIMIT 10001) s"),
            ("reltuples", "SELECT reltuples::bigint FROM pg_class WHERE oid = 'orders'::regclass"),
        ]:
            ms, rows = await timed(conn, q)
            print(f"Q6 {name}: {ms:.2f} ms -> {rows[0][0]}")
        t0 = time.perf_counter()
        est = (await conn.execute(text("EXPLAIN (FORMAT JSON) SELECT 1 FROM orders WHERE status = 'paid'"))).scalar_one()
        print(f"Q6 EXPLAIN estimate (filtered): {(time.perf_counter() - t0) * 1000:.2f} ms -> {est[0]['Plan']['Plan Rows']}")
        actual = (await conn.execute(text("SELECT count(*) FROM orders WHERE status = 'paid'"))).scalar_one()
        print(f"   actual: {actual}")
        print(json.dumps({"rows": N, "pg": (await conn.execute(text("SHOW server_version"))).scalar_one()}))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
