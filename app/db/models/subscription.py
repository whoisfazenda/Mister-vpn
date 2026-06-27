"""VPNSubscription model — local mirror of an AdaptGroup subscription."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.db.models.mixins import TimestampMixin


class VPNSubscription(Base, TimestampMixin):
    __tablename__ = "vpn_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subscription_uuid: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subscription_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    plan_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    max_devices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    traffic_used_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User", lazy="selectin")

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.traffic_limit_bytes is None or self.traffic_limit_bytes <= 0

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @property
    def is_effectively_active(self) -> bool:
        return self.is_active and not self.is_frozen and not self.is_expired
