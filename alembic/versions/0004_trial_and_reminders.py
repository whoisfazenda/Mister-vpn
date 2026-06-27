"""add free trial flags

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-14 17:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("trial_claimed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "vpn_subscriptions",
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("vpn_subscriptions", "is_trial")
    op.drop_column("users", "trial_claimed")
