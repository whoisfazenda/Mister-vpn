"""add plan button style

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-01 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vpn_plan_snapshots",
        sa.Column("button_style", sa.String(length=16), nullable=False, server_default="primary"),
    )
    op.add_column(
        "vpn_plan_snapshots",
        sa.Column("button_emoji_key", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vpn_plan_snapshots", "button_emoji_key")
    op.drop_column("vpn_plan_snapshots", "button_style")
