"""OneAdmin's own tables (ADR-0012).

They are defined with SQLAlchemy **Core** on a private ``MetaData``: they never join the host
application's declarative registry, never show up in its ``Base.metadata``, and are created
only by ``oneadmin migrate`` (the packaged Alembic environment in ``auth/migrations``).

Every name starts with ``oneadmin_``. Host apps exclude them from their own autogenerate with
``oneadmin.alembic.include_object``.

Keep this module and the migrations in sync. ``tests/integration/test_migrations_pg.py``
fails if they drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

PREFIX = "oneadmin_"
VERSION_TABLE = "oneadmin_alembic_version"

#: BIGINT everywhere, except SQLite where only INTEGER PRIMARY KEY auto-increments.
_ID = BigInteger().with_variant(Integer(), "sqlite")
#: JSONB on PostgreSQL (indexable, compact), JSON elsewhere.
_JSON = JSON().with_variant(JSONB(), "postgresql")


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware UTC timestamp on every backend.

    PostgreSQL's ``timestamptz`` round-trips aware datetimes, but SQLite has no time zone
    support: ``DateTime(timezone=True)`` comes back *naive* there, and comparing it with an
    aware "now" raises ``TypeError``. This type stores UTC everywhere (naive on SQLite) and
    always returns aware UTC datetimes, so the auth code never sees the difference.
    The DDL is plain ``DateTime(timezone=True)``, so migrations are unaffected.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("oneadmin stores aware datetimes only; got a naive one")
        utc = value.astimezone(UTC)
        return utc.replace(tzinfo=None) if dialect.name == "sqlite" else utc

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected a datetime from the database, got {type(value).__name__}")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

user = Table(
    "oneadmin_user",
    metadata,
    Column("id", _ID, primary_key=True),
    Column("email", String(254), nullable=False, unique=True, comment="normalised: lower-case"),
    Column("password_hash", String(255), nullable=False),
    Column("is_superuser", Boolean, nullable=False, default=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("password_changed_at", UTCDateTime(), nullable=False),
    Column("last_login_at", UTCDateTime(), nullable=True),
)

session = Table(
    "oneadmin_session",
    metadata,
    Column("token_hash", String(64), primary_key=True, comment="sha256 hex of the cookie token"),
    Column(
        "user_id",
        BigInteger,
        ForeignKey("oneadmin_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_seen_at", UTCDateTime(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False, comment="absolute expiry"),
    Column("ip", String(45), nullable=True),
    Column("user_agent", String(255), nullable=True),
)

login_attempt = Table(
    "oneadmin_login_attempt",
    metadata,
    Column("id", _ID, primary_key=True),
    Column("key", String(300), nullable=False, comment="'email:<addr>' or 'ip:<addr>'"),
    Column("at", UTCDateTime(), nullable=False),
    Column("success", Boolean, nullable=False),
    Index("ix_oneadmin_login_attempt_key_at", "key", "at"),
)

grant = Table(
    "oneadmin_grant",
    metadata,
    Column(
        "user_id",
        BigInteger,
        ForeignKey("oneadmin_user.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("codename", String(150), nullable=False, comment="e.g. 'orders.change'"),
    PrimaryKeyConstraint("user_id", "codename"),
)
"""Permissions granted to built-in users (ADR-0019). Superusers need none."""

audit_log = Table(
    "oneadmin_audit_log",
    metadata,
    Column("id", _ID, primary_key=True),
    Column("at", UTCDateTime(), nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("actor_email", String(254), nullable=False),
    Column("action", String(80), nullable=False, comment="create, update, delete, action:<name>"),
    Column("model", String(64), nullable=False, comment="the admin's slug"),
    Column("object_pk", String(512), nullable=False, comment="encoded primary key"),
    Column("changes", _JSON, nullable=False, comment="{field: [old, new]}"),
    Column("ip", String(45), nullable=True),
    Index("ix_oneadmin_audit_log_model_object_pk_at", "model", "object_pk", "at"),
    Index("ix_oneadmin_audit_log_at", "at"),
)
"""Append-only record of every change made through the admin (ADR-0018).

Written in the same transaction as the change it describes."""
