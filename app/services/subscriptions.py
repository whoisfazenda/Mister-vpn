"""Subscription service — sync AdaptGroup subscription state into the DB and
expose actions (freeze/unfreeze, devices, renew, etc.).

Network/charge errors propagate as AdaptGroup* exceptions for the handler
layer to translate into friendly messages.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.adaptgroup import AdaptGroupVPNClient, _first
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.subscription import VPNSubscription
from app.repositories.subscriptions import SubscriptionRepository

logger = get_logger(__name__)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        v = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _build_subscription_url(subscription_uuid: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    base = settings.adaptgroup_base_url.rstrip("/")
    return f"{base}/sub/{subscription_uuid}"


class SubscriptionService:
    def __init__(self, session: AsyncSession, client: AdaptGroupVPNClient) -> None:
        self.session = session
        self.client = client
        self.repo = SubscriptionRepository(session)

    async def get_user_subscription(self, user_id: int) -> VPNSubscription | None:
        return await self.repo.get_active_for_user(user_id)

    def apply_status_payload(
        self, sub: VPNSubscription, data: dict[str, Any]
    ) -> VPNSubscription:
        """Map a tolerant AdaptGroup status/create payload onto a subscription row."""
        inner = data.get("subscription") if isinstance(data.get("subscription"), dict) else data

        uuid = _first(inner, "subscription_uuid", "uuid", "id", "subscription_id")
        if uuid:
            sub.subscription_uuid = str(uuid)

        url = _first(inner, "subscription_url", "sub_url", "url")
        sub.subscription_url = _build_subscription_url(sub.subscription_uuid, url)

        plan_uuid = _first(inner, "plan_uuid", "new_plan_uuid", "plan_id", "plan")
        if plan_uuid:
            sub.plan_uuid = str(plan_uuid)
        plan_name = _first(inner, "plan_name", "plan_title")
        if plan_name:
            sub.plan_name = str(plan_name)

        starts = _parse_dt(_first(inner, "starts_at", "start_at", "created_at", "start_date"))
        expires = _parse_dt(_first(inner, "expires_at", "expire_at", "end_at", "end_date", "valid_until"))
        if starts:
            sub.starts_at = starts
        if expires:
            sub.expires_at = expires

        devices = _first(inner, "devices", "max_devices", "device_limit", "devices_limit")
        if devices is not None:
            try:
                sub.max_devices = int(devices)
            except (TypeError, ValueError):
                pass

        t_limit = _first(inner, "traffic_limit_bytes", "traffic_bytes", "data_limit_bytes")
        if t_limit is None:
            t_limit_gb = _first(inner, "traffic_limit_gb", "traffic_gb", "data_limit_gb")
            if t_limit_gb is not None:
                try:
                    t_limit = int(float(t_limit_gb) * (1024 ** 3))
                except (TypeError, ValueError):
                    t_limit = None
        if t_limit is not None:
            try:
                sub.traffic_limit_bytes = int(t_limit)
            except (TypeError, ValueError):
                pass

        t_used = _first(inner, "used_traffic_bytes", "traffic_used_bytes", "used_bytes", "traffic_used")
        if t_used is None:
            t_used_gb = _first(inner, "traffic_used_gb", "used_gb")
            if t_used_gb is not None:
                try:
                    t_used = int(float(t_used_gb) * (1024 ** 3))
                except (TypeError, ValueError):
                    t_used = None
        if t_used is not None:
            try:
                sub.traffic_used_bytes = int(t_used)
            except (TypeError, ValueError):
                pass

        frozen = _first(inner, "is_frozen", "frozen", "is_paused", "paused")
        if frozen is not None:
            sub.is_frozen = bool(frozen)
        frozen_at = _parse_dt(_first(inner, "frozen_at"))
        if frozen_at:
            sub.frozen_at = frozen_at
        active = _first(inner, "is_active", "active", "enabled")
        if active is not None:
            sub.is_active = bool(active)

        sub.last_synced_at = datetime.now(timezone.utc)
        return sub

    async def refresh_from_api(self, sub: VPNSubscription) -> VPNSubscription:
        """Pull the latest status from AdaptGroup and persist it."""
        await self.client.start()
        data = await self.client.get_status(sub.subscription_uuid)
        self.apply_status_payload(sub, data)
        await self.session.commit()
        return sub

    async def get_devices(self, sub: VPNSubscription) -> list[dict[str, Any]]:
        await self.client.start()
        raw = await self.client.get_devices(sub.subscription_uuid)
        result: list[dict[str, Any]] = []
        for d in raw:
            device_os = _first(d, "device_os", "os", "platform")
            device_model = _first(d, "device_model", "model")
            fallback_name = " ".join(
                str(part) for part in (device_os, device_model) if part
            ).strip()
            result.append(
                {
                    "id": str(_first(d, "id", "device_id", "uuid", default="")),
                    "name": str(
                        _first(
                            d,
                            "name",
                            "device_name",
                            default=fallback_name or "Устройство",
                        )
                    ),
                    "hwid": _first(d, "hwid"),
                    "device_os": device_os,
                    "device_model": device_model,
                    "ip_address": _first(d, "ip_address"),
                    "last_seen": _first(d, "last_seen", "last_active", "updated_at"),
                    "raw": d,
                }
            )
        return result

    async def delete_device(self, sub: VPNSubscription, device_id: str) -> None:
        await self.client.start()
        await self.client.delete_device(sub.subscription_uuid, device_id)

    async def freeze(self, sub: VPNSubscription) -> None:
        await self.client.start()
        await self.client.freeze_subscription(sub.subscription_uuid)
        sub.is_frozen = True
        sub.frozen_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def unfreeze(self, sub: VPNSubscription) -> None:
        await self.client.start()
        await self.client.unfreeze_subscription(sub.subscription_uuid)
        sub.is_frozen = False
        sub.frozen_at = None
        await self.session.commit()
