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
    op.add_column(
        "users",
        sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("balance_currency", sa.String(length=8), nullable=False, server_default="RUB"),
    )


def downgrade() -> None:
    op.drop_column("users", "balance_currency")
    op.drop_column("users", "balance")
