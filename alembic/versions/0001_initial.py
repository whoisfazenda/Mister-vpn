"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-10 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="ru"),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="user"),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("balance_currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "vpn_plan_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("plan_uuid", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("purchase_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("retail_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("manual_price", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vpn_plan_snapshots_plan_uuid", "vpn_plan_snapshots", ["plan_uuid"], unique=True)

    op.create_table(
        "vpn_subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_uuid", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_url", sa.String(length=512), nullable=True),
        sa.Column("plan_uuid", sa.String(length=64), nullable=True),
        sa.Column("plan_name", sa.String(length=255), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_devices", sa.Integer(), nullable=True),
        sa.Column("traffic_limit_bytes", sa.BigInteger(), nullable=True),
        sa.Column("traffic_used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vpn_subscriptions_subscription_uuid", "vpn_subscriptions", ["subscription_uuid"], unique=True)
    op.create_index("ix_vpn_subscriptions_user_id", "vpn_subscriptions", ["user_id"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("payment_provider", sa.String(length=32), nullable=False, server_default="mock"),
        sa.Column("payment_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("subscription_uuid", sa.String(length=64), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("needs_manual_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_order_uuid", "orders", ["order_uuid"], unique=True)
    op.create_index("ix_orders_user_id", "orders", ["user_id"], unique=False)
    op.create_index("ix_orders_status", "orders", ["status"], unique=False)
    op.create_index("ix_orders_payment_id", "orders", ["payment_id"], unique=False)
    op.create_index("ix_orders_idempotency_key", "orders", ["idempotency_key"], unique=True)

    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="adaptgroup"),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"], unique=False)
    op.create_index("ix_webhook_events_event_key", "webhook_events", ["event_key"], unique=True)

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_index("ix_webhook_events_event_key", table_name="webhook_events")
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("ix_orders_idempotency_key", table_name="orders")
    op.drop_index("ix_orders_payment_id", table_name="orders")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_index("ix_orders_order_uuid", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_vpn_subscriptions_user_id", table_name="vpn_subscriptions")
    op.drop_index("ix_vpn_subscriptions_subscription_uuid", table_name="vpn_subscriptions")
    op.drop_table("vpn_subscriptions")
    op.drop_index("ix_vpn_plan_snapshots_plan_uuid", table_name="vpn_plan_snapshots")
    op.drop_table("vpn_plan_snapshots")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
