"""OneAdmin initial tables: users, sessions, login attempts.

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "oneadmin_user",
        sa.Column("id", _ID, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, comment="normalised: lower-case"),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_superuser", sa.Boolean, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_oneadmin_user"),
        sa.UniqueConstraint("email", name="uq_oneadmin_user_email"),
    )
    op.create_table(
        "oneadmin_session",
        sa.Column(
            "token_hash", sa.String(64), nullable=False, comment="sha256 hex of the cookie token"
        ),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False, comment="absolute expiry"
        ),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("token_hash", name="pk_oneadmin_session"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["oneadmin_user.id"],
            name="fk_oneadmin_session_user_id_oneadmin_user",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_oneadmin_session_user_id", "oneadmin_session", ["user_id"])
    op.create_table(
        "oneadmin_login_attempt",
        sa.Column("id", _ID, primary_key=True),
        sa.Column("key", sa.String(300), nullable=False, comment="'email:<addr>' or 'ip:<addr>'"),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_oneadmin_login_attempt"),
    )
    op.create_index("ix_oneadmin_login_attempt_key_at", "oneadmin_login_attempt", ["key", "at"])


def downgrade() -> None:
    op.drop_table("oneadmin_login_attempt")
    op.drop_table("oneadmin_session")
    op.drop_table("oneadmin_user")
