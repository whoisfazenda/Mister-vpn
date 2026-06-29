"""add plan visibility controls

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-14 00:10:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not _has_column("vpn_plan_snapshots", "is_public"):
        op.add_column(
            "vpn_plan_snapshots",
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if not _has_column("vpn_plan_snapshots", "manual_price"):
        op.add_column(
            "vpn_plan_snapshots",
            sa.Column("manual_price", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if _has_column("vpn_plan_snapshots", "manual_price"):
        op.drop_column("vpn_plan_snapshots", "manual_price")
    if _has_column("vpn_plan_snapshots", "is_public"):
        op.drop_column("vpn_plan_snapshots", "is_public")


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
