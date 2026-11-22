"""Fast, deterministic seeding of the demo shop: one ``INSERT ... SELECT`` per table.

Rows are generated in the database from a recursive CTE (``n = 1..N``), so a million orders
take seconds rather than minutes, and no SQL text is written by hand: the statements are
SQLAlchemy Core and work on SQLite and PostgreSQL.

Every value is a pure function of ``n``, so the same ``--rows`` always produces the same data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Numeric,
    String,
    case,
    cast,
    func,
    insert,
    literal,
    select,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from oneadmin.demo.models import Category, Customer, Order, Product

START = datetime(2025, 1, 1)
CATEGORIES = (
    "Books", "Music", "Garden", "Kitchen", "Toys", "Sports",
    "Outdoors", "Office", "Beauty", "Health", "Games", "Tools",
)  # fmt: skip
COUNTRIES = ("DE", "FR", "GB", "US", "IN", "BR", "JP", "NL")
PRODUCTS = 500


def customers_for(rows: int) -> int:
    return max(100, rows // 100)


async def seed(conn: AsyncConnection, rows: int) -> None:
    """Fill the (empty) demo tables: ``rows`` orders, and customers/products to match."""
    customers = customers_for(rows)
    await conn.execute(insert(Category), [{"name": name} for name in CATEGORIES])
    await conn.execute(_customers(conn, customers))
    await conn.execute(_products(conn))
    await conn.execute(_orders(conn, rows, customers))


def _seq(n: int, name: str) -> Any:
    """``n`` as rows 1..n: a recursive CTE (portable; the database generates the rows)."""
    # BIGINT: products like n * 31_536_000 overflow a 32-bit INTEGER on PostgreSQL.
    seq = select(literal(1, BigInteger).label("n")).cte(name, recursive=True)
    return seq.union_all(select(seq.c.n + 1).where(seq.c.n < n))


def _text(prefix: str, n: Any, suffix: str = "") -> Any:
    out = literal(prefix, String) + cast(n, String)
    return out + literal(suffix, String) if suffix else out


def _pick(n: Any, choices: tuple[str, ...]) -> Any:
    return case(*((n % len(choices) == i, c) for i, c in enumerate(choices)), else_=choices[0])


def _timestamp(conn: AsyncConnection, seconds: Any) -> Any:
    """``START + seconds``, stored exactly as SQLAlchemy binds datetimes on this dialect."""
    if conn.dialect.name == "sqlite":
        # SQLite stores DATETIME as text; SQLAlchemy writes "%Y-%m-%d %H:%M:%S.%f". Seeded rows
        # must use the same format, or text comparisons (keyset cursors) go wrong.
        base = func.datetime(literal(START.isoformat(sep=" ")), _text("+", seconds, " seconds"))
        return base + literal(".000000", String)
    return cast(literal(START), DateTime) + func.make_interval(0, 0, 0, 0, 0, 0, seconds)


def _customers(conn: AsyncConnection, count: int) -> Any:
    n = _seq(count, "c").c.n
    return insert(Customer).from_select(
        ["name", "email", "country", "is_vip", "created_at"],
        select(
            _text("Customer ", n),
            _text("customer", n, "@example.com"),
            _pick(n, COUNTRIES),
            n % 20 == 0,
            _timestamp(conn, n * 600),
        ),
    )


def _products(conn: AsyncConnection) -> Any:
    n = _seq(PRODUCTS, "p").c.n
    return insert(Product).from_select(
        ["sku", "name", "price", "active", "category_id"],
        select(
            _text("SKU-", n + 10000),
            _text("Product ", n),
            cast((n % 200 + 1) * 1.25, Numeric(10, 2)),
            n % 10 != 0,
            n % len(CATEGORIES) + 1,
        ),
    )


def _orders(conn: AsyncConnection, rows: int, customers: int) -> Any:
    n = _seq(rows, "o").c.n
    status = cast(
        case(
            (n % 10 == 0, "cancelled"),
            (n % 10 < 4, "new"),
            (n % 10 < 7, "paid"),
            else_="shipped",
        ),
        Order.__table__.c.status.type,
    )
    return insert(Order).from_select(
        ["customer_id", "product_id", "quantity", "status", "total", "created_at", "note"],
        select(
            (n * 7919) % customers + 1,
            n % PRODUCTS + 1,
            n % 5 + 1,
            status,
            cast((n % 20000) / 100.0 + 5, Numeric(12, 2)),
            # spread over about a year, so date filters have something to do
            _timestamp(conn, (n * 31_536_000) // max(rows, 1)),
            case((n % 50 == 0, "Gift wrap, please"), else_=None),
        ),
    )
