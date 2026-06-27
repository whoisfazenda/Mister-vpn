"""VPNPlanSnapshot model — cached snapshot of an AdaptGroup plan."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class VPNPlanSnapshot(Base):
    """A point-in-time snapshot of a plan from POST /plans/list.

    ``traffic_limit_bytes`` NULL means unlimited traffic.
    Prices are stored as Numeric to avoid float drift.
    """

    __tablename__ = "vpn_plan_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_uuid: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Внутренняя закупочная цена сервиса — НЕ показывать пользователю.
    purchase_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Розничная цена для пользователя.
    retail_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_devices: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic_limit_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    period_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_price: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manual_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def is_unlimited_traffic(self) -> bool:
        return self.traffic_limit_bytes is None or self.traffic_limit_bytes <= 0
