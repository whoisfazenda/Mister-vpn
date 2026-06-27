"""Background monitor that notifies users about newly seen VPN devices."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.bot.deps import get_client
from app.core.config import settings
from app.core.logging import get_logger
from app.db.database import async_session_factory
from app.db.models.subscription import VPNSubscription
from app.repositories.settings import SettingsRepository
from app.services.device_keys import device_seen_key
from app.services.notifications import NotificationService
from app.services.subscriptions import SubscriptionService

logger = get_logger(__name__)


async def run_device_monitor_loop(bot: Bot) -> None:
    interval = max(30, settings.device_monitor_interval_seconds)
    while True:
        try:
            await check_new_devices(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Device monitor check failed")
        await asyncio.sleep(interval)


async def check_new_devices(bot: Bot) -> int:
    now = datetime.now(timezone.utc)
    sent = 0
    async with async_session_factory() as session:
        result = await session.execute(
            select(VPNSubscription)
            .options(selectinload(VPNSubscription.user))
            .where(VPNSubscription.is_active.is_(True))
            .where(VPNSubscription.is_frozen.is_(False))
            .where(
                or_(
                    VPNSubscription.expires_at.is_(None),
                    VPNSubscription.expires_at > now,
                )
            )
        )
        subs = list(result.scalars().all())
        repo = SettingsRepository(session)
        service = SubscriptionService(session, get_client())
        notifier = NotificationService(bot)

        for sub in subs:
            if sub.user is None:
                continue
            try:
                devices = await service.get_devices(sub)
            except Exception as exc:  # noqa: BLE001
                logger.info("Could not load devices for %s: %s", sub.subscription_uuid, exc)
                continue

            for device in devices:
                details = _device_details(device)
                key = device_seen_key(
                    sub.subscription_uuid,
                    hwid=details.get("hwid"),
                    device_id=details.get("id"),
                )
                if not key or await repo.get(key):
                    continue
                await repo.set(key, "1", "Seen AdaptGroup device notification")
                await session.flush()
                if await notifier.notify_event(
                    sub.user.telegram_id,
                    "subs.device_connected",
                    details,
                ):
                    sent += 1
        await session.commit()
    return sent


def _device_details(device: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(device.get("id") or ""),
        "name": str(device.get("name") or "Устройство"),
        "hwid": str(device.get("hwid") or ""),
        "device_os": str(device.get("device_os") or ""),
        "device_model": str(device.get("device_model") or ""),
        "ip_address": str(device.get("ip_address") or ""),
    }
