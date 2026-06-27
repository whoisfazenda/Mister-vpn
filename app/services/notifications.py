"""Notification service — sends user-facing notifications and admin alerts."""
from __future__ import annotations

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.bot.premium_emoji import pe
from app.bot.keyboards.factory import inline_keyboard
from app.core.config import settings
from app.core.logging import get_logger
from app.services.webhooks import DEVICE_ADDED_EVENTS
from app.utils.formatting import escape

logger = get_logger(__name__)


# ── event → message text + button ───────────────────────────
_EXPIRY_EVENTS = {
    "subs.expires_in_72_hours": "через 72 часа",
    "subs.expires_in_48_hours": "через 48 часов",
    "subs.expires_in_24_hours": "через 24 часа",
}


def _expiry_message(when: str) -> tuple[str, list]:
    text = (
        f"{pe('time')} <b>Подписка скоро закончится</b>\n\n"
        f"Ваш VPN перестанет работать {when}.\n"
        f"Продлите подписку, чтобы не потерять доступ."
    )
    buttons = [[("♻️ Продлить", "renew:menu", "success")]]
    return text, buttons


def _expired_message() -> tuple[str, list]:
    text = (
        f"{pe('inactive')} <b>Подписка истекла</b>\n\n"
        "Доступ к VPN приостановлен. Продлите подписку, чтобы продолжить пользоваться сервисом."
    )
    buttons = [[("♻️ Продлить", "renew:menu", "success")]]
    return text, buttons


def _expired_yesterday_message() -> tuple[str, list]:
    text = (
        f"{pe('inactive')} <b>Подписка истекла вчера</b>\n\n"
        "Вы всё ещё можете продлить её и вернуть доступ к VPN."
    )
    buttons = [[("♻️ Продлить", "renew:menu", "success")]]
    return text, buttons


def _traffic_message() -> tuple[str, list]:
    text = (
        f"{pe('traffic')} <b>Заканчивается трафик</b>\n\n"
        "Вы почти израсходовали лимит трафика. Докупите гигабайты, чтобы скорость не снижалась."
    )
    buttons = [[("⚡ Докупить трафик", "traffic:menu", "primary")]]
    return text, buttons


def _device_added_message(details: dict | None = None) -> tuple[str, list]:
    details = details or {}
    name = details.get("name") or "Устройство"
    hwid = details.get("hwid") or "—"
    device_os = details.get("device_os") or "—"
    model = details.get("device_model") or "—"
    ip = details.get("ip_address") or "—"
    text = (
        f"{pe('devices')} <b>Добавлено новое устройство</b>\n\n"
        f"Название: <b>{escape(name)}</b>\n"
        f"HWID: <code>{escape(hwid)}</code>\n"
        f"Система: <b>{escape(device_os)}</b>\n"
        f"Модель: <b>{escape(model)}</b>\n"
        f"IP: <b>{escape(ip)}</b>\n\n"
        "Если это были не вы, откройте устройства и удалите лишнее подключение."
    )
    buttons = [[("📱 Мои устройства", "profile:subs", "primary")]]
    return text, buttons


def build_event_notification(event_type: str, details: dict | None = None) -> tuple[str, list] | None:
    if event_type in DEVICE_ADDED_EVENTS:
        return _device_added_message(details)
    if event_type in _EXPIRY_EVENTS:
        return _expiry_message(_EXPIRY_EVENTS[event_type])
    if event_type == "subs.expired":
        return _expired_message()
    if event_type == "subs.expired_24_hours_ago":
        return _expired_yesterday_message()
    if event_type == "subs.traffic_threshold_reached":
        return _traffic_message()
    return None


class NotificationService:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def notify_event(
        self,
        telegram_id: int,
        event_type: str,
        details: dict | None = None,
    ) -> bool:
        built = build_event_notification(event_type, details)
        if built is None:
            return False
        text, buttons = built
        try:
            await self.bot.send_message(
                telegram_id,
                text,
                reply_markup=inline_keyboard(buttons),
            )
            return True
        except TelegramAPIError as exc:
            logger.warning("Failed to notify user %s: %s", telegram_id, exc)
            return False

    async def alert_admins(self, text: str) -> None:
        """Send a critical alert to all configured admins."""
        for admin_id in settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, f"🚨 <b>Алерт</b>\n\n{text}")
            except TelegramAPIError as exc:
                logger.warning("Failed to alert admin %s: %s", admin_id, exc)
