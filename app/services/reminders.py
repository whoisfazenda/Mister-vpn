"""Background subscription-expiration reminders."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.bot.keyboards.factory import make_button
from app.bot.premium_emoji import pe
from app.db.database import async_session_factory
from app.db.models.subscription import VPNSubscription
from app.repositories.settings import SettingsRepository
from app.utils.formatting import format_date

logger = get_logger(__name__)


async def run_subscription_reminder_loop(bot: Bot) -> None:
    """Periodically send one-time reminders before subscription expiry."""
    interval = max(300, settings.reminder_check_interval_seconds)
    while True:
        try:
            await send_due_subscription_reminders(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Subscription reminder check failed")
        await asyncio.sleep(interval)


async def send_due_subscription_reminders(bot: Bot) -> int:
    """Send all due reminders and return the number of messages sent."""
    now = datetime.now(timezone.utc)
    sent = 0
    async with async_session_factory() as session:
        repo = SettingsRepository(session)
        result = await session.execute(
            select(VPNSubscription)
            .options(selectinload(VPNSubscription.user))
            .where(VPNSubscription.is_active.is_(True))
            .where(VPNSubscription.expires_at.is_not(None))
        )
        for sub in result.scalars().all():
            if sub.expires_at is None:
                continue
            expires_at = _aware_utc(sub.expires_at)
            if expires_at <= now:
                continue
            for days in _thresholds_for(sub):
                if not (timedelta() < expires_at - now <= timedelta(days=days)):
                    continue
                key = f"subscription_reminder:{sub.id}:{days}"
                if await repo.get(key):
                    continue
                await bot.send_message(
                    sub.user.telegram_id,
                    _reminder_text(sub, days),
                    reply_markup=_reminder_keyboard(sub),
                )
                await repo.set(key, "sent")
                sent += 1
        await session.commit()
    return sent


def _thresholds_for(sub: VPNSubscription) -> tuple[int, ...]:
    return (1,) if sub.is_trial else (7, 2, 1)


def _reminder_text(sub: VPNSubscription, days: int) -> str:
    if sub.is_trial:
        return (
            f"{pe('gift')} <b>Пробный период почти закончился</b>\n\n"
            "Остался 1 день бесплатного доступа. Чтобы VPN не отключился, "
            "выберите основной тариф и оплатите подписку.\n\n"
            f"Текущая подписка действует до: <b>{format_date(sub.expires_at)}</b>"
        )
    day_word = "день" if days == 1 else "дня" if days in (2, 3, 4) else "дней"
    return (
        f"{pe('time')} <b>Подписка скоро закончится</b>\n\n"
        f"До окончания осталось <b>{days} {day_word}</b>. "
        "Продлите доступ заранее, чтобы VPN работал без паузы.\n\n"
        f"Действует до: <b>{format_date(sub.expires_at)}</b>"
    )


def _reminder_keyboard(sub: VPNSubscription) -> InlineKeyboardMarkup:
    if sub.is_trial:
        rows = [[make_button("🛒 Купить VPN", "buy:list", "success")]]
    else:
        rows = [[make_button("♻️ Продлить", "renew:menu", "success")]]
    rows.append([make_button("👤 Профиль", "profile:open", "primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
