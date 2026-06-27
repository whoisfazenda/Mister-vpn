"""add plan period groups

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-15 19:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vpn_plan_snapshots",
        sa.Column("period_group", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vpn_plan_snapshots", "period_group")
