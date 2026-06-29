"""add user balance

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not _has_column("users", "balance"):
        op.add_column(
            "users",
            sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        )
    if not _has_column("users", "balance_currency"):
        op.add_column(
            "users",
            sa.Column("balance_currency", sa.String(length=8), nullable=False, server_default="RUB"),
        )


def downgrade() -> None:
    if _has_column("users", "balance_currency"):
        op.drop_column("users", "balance_currency")
    if _has_column("users", "balance"):
        op.drop_column("users", "balance")


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
