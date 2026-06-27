"""Order model — the unit of payment + provisioning idempotency."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import OrderStatus, OrderType
from app.db.database import Base
from app.db.models.mixins import TimestampMixin


class Order(Base, TimestampMixin):
    """An order ties a payment to a single AdaptGroup provisioning action.

    ``snapshot`` freezes purchase parameters (plan uuid, name, price, days,
    devices, traffic, target subscription uuid) so they cannot change after
    creation. ``idempotency_key`` guards against duplicate provisioning.
    """

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_uuid: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_type: Mapped[OrderType] = mapped_column(String(32), nullable=False)

    # Snapshot of purchase parameters at order-creation time.
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)

    payment_provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    status: Mapped[OrderStatus] = mapped_column(
        String(20), default=OrderStatus.PENDING, index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )

    # Subscription this order targets / produced.
    subscription_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when payment succeeded but provisioning failed → needs human review.
    needs_manual_review: Mapped[bool] = mapped_column(
        default=False, nullable=False
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", lazy="selectin")
