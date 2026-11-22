"""Small, controllable models for query-engine tests (kept apart from the example app)."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Computed,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TBase(DeclarativeBase):
    pass


class Color(enum.Enum):
    RED = "red"
    GREEN = "green"
    BLUE = "blue"


class Lowercase(TypeDecorator[str]):
    impl = String(50)
    cache_ok = True


class Item(TBase):
    __tablename__ = "qe_item"
    __table_args__ = (
        Index("ix_qe_item_grp_id", "grp", "id"),
        Index("ix_qe_item_seen_id", "seen_at", "id"),
        Index("ix_qe_item_tenant_grp_id", "tenant", "grp", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant: Mapped[int] = mapped_column(Integer)
    grp: Mapped[int] = mapped_column(Integer)
    """Few distinct values: lots of duplicates, so the PK tiebreak is exercised."""
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Nullable sort key."""
    name: Mapped[str] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    color: Mapped[Color] = mapped_column(Enum(Color, name="qe_color"))
    slug: Mapped[str | None] = mapped_column(Lowercase)
    doubled: Mapped[int] = mapped_column(Integer, Computed("grp * 2", persisted=True))


class Pair(TBase):
    """Composite primary key."""

    __tablename__ = "qe_pair"

    a: Mapped[int] = mapped_column(Integer, primary_key=True)
    b: Mapped[str] = mapped_column(String(10), primary_key=True)
    v: Mapped[int] = mapped_column(Integer)


class Staff(TBase):
    """Has sensitive-looking columns that must never reach the API by default."""

    __tablename__ = "qe_staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(200))
    api_token: Mapped[str | None] = mapped_column(String(200))
