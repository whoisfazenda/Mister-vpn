"""Webhook event repository — idempotent insert by event_key."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.webhook_event import WebhookEvent
from app.repositories.base import BaseRepository


class WebhookEventRepository(BaseRepository):
    async def get_by_key(self, event_key: str) -> WebhookEvent | None:
        res = await self.session.execute(
            select(WebhookEvent).where(WebhookEvent.event_key == event_key)
        )
        return res.scalar_one_or_none()

    async def create(
        self,
        *,
        event_type: str,
        event_key: str,
        payload: dict,
        source: str = "adaptgroup",
    ) -> WebhookEvent:
        event = WebhookEvent(
            source=source,
            event_type=event_type,
            event_key=event_key,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def mark_processed(
        self, event: WebhookEvent, result: str, error_text: str | None = None
    ) -> None:
        event.result = result
        event.error_text = error_text[:2000] if error_text else None
        event.processed_at = datetime.now(timezone.utc)

    async def mark_notified(self, event: WebhookEvent) -> None:
        event.notified = True
