"""WebhookEvent model — idempotent processing log for inbound webhooks."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), default="adaptgroup", nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # Stable unique key for dedup (hash of raw body, or provider event id).
    event_key: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True once a user-facing notification has been sent for this event.
    notified: Mapped[bool] = mapped_column(default=False, nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
