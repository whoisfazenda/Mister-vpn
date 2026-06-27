"""Webhook service — idempotent processing of AdaptGroup subscription events.

Signature verification happens in the FastAPI route (on the raw body) BEFORE
this service is invoked. This service handles dedup, persistence and deciding
which user notification to send.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.adaptgroup import AdaptGroupVPNClient, _first
from app.core.enums import WebhookProcessResult
from app.core.logging import get_logger
from app.repositories.settings import SettingsRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.repositories.webhook_events import WebhookEventRepository
from app.services.device_keys import device_seen_key
from app.services.subscriptions import SubscriptionService

logger = get_logger(__name__)

DEVICE_ADDED_EVENTS = frozenset(
    {
        "subs.device_added",
        "subs.device_created",
        "subs.device_connected",
        "subs.device_registered",
        "device.added",
        "device.created",
        "device.connected",
        "devices.added",
        "devices.created",
    }
)

SUPPORTED_EVENTS = frozenset(
    {
        "subs.created",
        "subs.renewed",
        "subs.upgraded",
        "subs.traffic_purchased",
        "subs.expires_in_72_hours",
        "subs.expires_in_48_hours",
        "subs.expires_in_24_hours",
        "subs.expired",
        "subs.expired_24_hours_ago",
        "subs.traffic_threshold_reached",
    }
) | DEVICE_ADDED_EVENTS

# Events that should trigger a user notification.
NOTIFY_EVENTS = frozenset(
    {
        "subs.expires_in_72_hours",
        "subs.expires_in_48_hours",
        "subs.expires_in_24_hours",
        "subs.expired",
        "subs.expired_24_hours_ago",
        "subs.traffic_threshold_reached",
    }
) | DEVICE_ADDED_EVENTS


def compute_event_key(event_type: str, raw_body: bytes, payload: dict[str, Any]) -> str:
    """Stable dedup key.

    Prefers a provider-supplied event id; otherwise hashes type+timestamp+data,
    falling back to a hash of the raw body.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    event_id = None
    if isinstance(data, dict):
        event_id = _first(data, "event_id", "id", "uuid")
    timestamp = payload.get("timestamp") if isinstance(payload, dict) else None
    if event_id:
        return f"{event_type}:{event_id}"
    if timestamp and isinstance(data, dict):
        basis = json.dumps(
            {"t": event_type, "ts": timestamp, "d": data}, sort_keys=True, default=str
        ).encode("utf-8")
        return f"{event_type}:{hashlib.sha256(basis).hexdigest()}"
    return f"{event_type}:{hashlib.sha256(raw_body).hexdigest()}"


class NotificationIntent:
    """Describes a user notification the API layer should dispatch."""

    def __init__(
        self,
        telegram_id: int,
        event_type: str,
        subscription_uuid: str | None,
        details: dict[str, Any] | None = None,
    ):
        self.telegram_id = telegram_id
        self.event_type = event_type
        self.subscription_uuid = subscription_uuid
        self.details = details or {}


class WebhookService:
    def __init__(self, session: AsyncSession, client: AdaptGroupVPNClient) -> None:
        self.session = session
        self.client = client
        self.events = WebhookEventRepository(session)
        self.subs = SubscriptionRepository(session)
        self.settings = SettingsRepository(session)

    async def process(
        self, event_type: str, payload: dict[str, Any], raw_body: bytes
    ) -> tuple[WebhookProcessResult, NotificationIntent | None]:
        """Idempotently process one webhook event.

        Returns (result, optional notification intent). Duplicate events return
        DUPLICATE and never produce a second notification.
        """
        event_key = compute_event_key(event_type, raw_body, payload)

        existing = await self.events.get_by_key(event_key)
        if existing is not None:
            logger.info("Duplicate webhook %s ignored", event_type)
            return WebhookProcessResult.DUPLICATE, None

        event = await self.events.create(
            event_type=event_type, event_key=event_key, payload=payload
        )

        if event_type not in SUPPORTED_EVENTS:
            await self.events.mark_processed(event, WebhookProcessResult.IGNORED)
            await self.session.commit()
            return WebhookProcessResult.IGNORED, None

        intent: NotificationIntent | None = None
        try:
            intent = await self._handle_event(event_type, payload)
            await self.events.mark_processed(event, WebhookProcessResult.PROCESSED)
        except Exception as exc:  # noqa: BLE001 — record & swallow, ack 200
            await self.events.mark_processed(
                event, WebhookProcessResult.ERROR, error_text=str(exc)
            )
            await self.session.commit()
            logger.exception("Webhook %s processing error", event_type)
            return WebhookProcessResult.ERROR, None

        # Mark notified before sending is acceptable here because dedup is on
        # the event row; the API layer only notifies when intent is returned
        # and this row is freshly created (not a duplicate).
        if intent is not None:
            await self.events.mark_notified(event)
        await self.session.commit()
        return WebhookProcessResult.PROCESSED, intent

    async def _handle_event(
        self, event_type: str, payload: dict[str, Any]
    ) -> NotificationIntent | None:
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            data = {}

        sub_uuid = _first(
            data, "subscription_id", "subscription_uuid", "uuid", "id"
        )
        device = _extract_device(data)
        if not sub_uuid and device:
            sub_uuid = _first(device, "subscription_id", "subscription_uuid", "sub_uuid")
        external_user_id = _first(data, "external_user_id", "external_id")

        sub = None
        if sub_uuid:
            sub = await self.subs.get_by_uuid(str(sub_uuid))

        # Sync local subscription state from the payload when we know it.
        if sub is not None:
            sub_service = SubscriptionService(self.session, self.client)
            sub_service.apply_status_payload(sub, data)
            await self.session.flush()

        # Determine the telegram id to notify.
        telegram_id: int | None = None
        if external_user_id:
            try:
                telegram_id = int(external_user_id)
            except (TypeError, ValueError):
                telegram_id = None
        if telegram_id is None and sub is not None and sub.user is not None:
            telegram_id = sub.user.telegram_id

        if event_type in DEVICE_ADDED_EVENTS and telegram_id is not None:
            details = _device_details(device or data)
            device_key = device_seen_key(
                str(sub_uuid) if sub_uuid else None,
                hwid=details.get("hwid"),
                device_id=details.get("id"),
            )
            if device_key and await self.settings.get(device_key):
                return None
            if device_key:
                await self.settings.set(device_key, "1", "Seen AdaptGroup device notification")
            return NotificationIntent(
                telegram_id=telegram_id,
                event_type=event_type,
                subscription_uuid=str(sub_uuid) if sub_uuid else None,
                details=details,
            )

        if event_type in NOTIFY_EVENTS and telegram_id is not None:
            return NotificationIntent(
                telegram_id=telegram_id,
                event_type=event_type,
                subscription_uuid=str(sub_uuid) if sub_uuid else None,
            )
        return None


def _extract_device(data: dict[str, Any]) -> dict[str, Any] | None:
    device = data.get("device")
    if isinstance(device, dict):
        return device
    devices = data.get("devices")
    if isinstance(devices, list) and devices and isinstance(devices[0], dict):
        return devices[0]
    return None


def _device_details(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    return {
        "id": str(_first(data, "id", "device_id", "uuid", default="") or ""),
        "name": str(_first(data, "name", "device_name", default="Устройство") or "Устройство"),
        "hwid": str(_first(data, "hwid", "hardware_id", default="") or ""),
        "device_os": str(_first(data, "device_os", "os", "platform", default="") or ""),
        "device_model": str(_first(data, "device_model", "model", default="") or ""),
        "ip_address": str(_first(data, "ip_address", "ip", default="") or ""),
    }
