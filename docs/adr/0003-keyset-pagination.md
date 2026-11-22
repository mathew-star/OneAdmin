# 0003: Keyset pagination compiler

- Status: accepted (amended 2026-11-06 after M1 implementation)
- Date: 2026-11-06

## Context
The draft's `a > x OR (a = x AND pk > y)` predicate is as slow as OFFSET on PG17. Measured: 86 ms and 502k buffers, against 0.6 ms and 53 buffers for the bounded or row-value forms. Details in technical-findings §2. Row comparisons silently drop NULL rows.

## Decision
- The sort spec is always completed with every PK column (a total order).
- Predicate forms:
  - **Bounded nested form** (default; all dialects; mixed directions):
    `k1 ⋈= v1 AND (k1 ⋈ v1 OR (k2 ⋈= v2 AND (k2 ⋈ v2 OR …)))`
  - **Row-value form** `(k1..kn) > (v1..vn)`, PG only, for uniform-direction, non-null keys. It is an optimisation chosen by the dialect strategy.
- **Nullable leading sort key:** the predicate splits into at most two ordered *segments* (the non-null range and the IS NULL range, with explicit `NULLS FIRST/LAST`). They execute as one `UNION ALL` of individually LIMITed, index-friendly branches, ordered by segment. The segment is derived from whether the cursor's lead value is NULL, so no phase field is needed in the cursor.
- **PK tiebreaker:** appended PK columns inherit the direction of the last explicit key. `-created_at` becomes `(-created_at, -id)`, which stays uniform and so eligible for the row-value form.
- **OFFSET fallback** only for sorts on non-column expressions (hybrids, label expressions) or nullable non-leading keys. The response says `pagination: "offset"` and a startup warning is logged.
- **Cursors:** base64url(JSON `{v: [...] | o: offset, d: "after"|"before", s: sort_hash}`), HMAC-signed with the site secret. Tampering returns 400. A `s` mismatch (sort changed) returns 400, so a cursor can't be replayed against a different sort and produce an inconsistent predicate. Values are typed through `ModelMeta` before binding, never interpolated.
- **Backwards paging:** the comparison and ORDER BY are reversed, and the page is reversed in memory.
- Fetching `limit + 1` rows tells us whether there is a next page.

## Consequences
- No "jump to page 37" on keyset lists. The UI offers first/prev/next/last plus count.
- The "last page" link is a reversed first page.
- Plan-shape tests are required for every predicate form.

## Revisit when
The PG planner learns to turn the OR-expansion into a range, or users strongly need page jumps (offer an "approximate jump" via OFFSET with a warning).

## Verification (M1)
- `tests/integration/test_pagination_pg.py`:
  - Exhaustive forward and backward walks equal `ORDER BY` for 10 sort shapes, including composite PKs and filtered lists.
  - Plan-shape tests check for an `Index Cond` on the leading key.
- **Mutation check:** swapping in the draft's OR-expansion makes 7 plan tests fail.
- `benchmarks/README.md`: flat ~1.1 ms per page from depth 0 to 300k on 1M rows.
