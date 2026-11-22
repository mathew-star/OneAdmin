"""Permission grants and the audit log (ADR-0018, ADR-0019).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "oneadmin_grant",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("codename", sa.String(150), nullable=False, comment="e.g. 'orders.change'"),
        sa.PrimaryKeyConstraint("user_id", "codename", name="pk_oneadmin_grant"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["oneadmin_user.id"],
            name="fk_oneadmin_grant_user_id_oneadmin_user",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "oneadmin_audit_log",
        sa.Column("id", _ID, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("actor_email", sa.String(254), nullable=False),
        sa.Column(
            "action",
            sa.String(80),
            nullable=False,
            comment="create, update, delete, action:<name>",
        ),
        sa.Column("model", sa.String(64), nullable=False, comment="the admin's slug"),
        sa.Column("object_pk", sa.String(512), nullable=False, comment="encoded primary key"),
        sa.Column("changes", _JSON, nullable=False, comment="{field: [old, new]}"),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_oneadmin_audit_log"),
    )
    op.create_index(
        "ix_oneadmin_audit_log_model_object_pk_at",
        "oneadmin_audit_log",
        ["model", "object_pk", "at"],
    )
    op.create_index("ix_oneadmin_audit_log_at", "oneadmin_audit_log", ["at"])


def downgrade() -> None:
    op.drop_table("oneadmin_audit_log")
    op.drop_table("oneadmin_grant")
