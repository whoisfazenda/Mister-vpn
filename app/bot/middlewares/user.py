"""User middleware — upserts the user and injects it; blocks banned users."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from app.bot.keyboards.factory import make_button, make_url_button
from app.bot.premium_emoji import pe
from app.core.config import settings
from app.repositories.users import UserRepository


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session = data.get("session")
        if tg_user is None or session is None:
            return await handler(event, data)

        repo = UserRepository(session)
        user = await repo.get_or_create(
            telegram_id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            language=(tg_user.language_code or "ru"),
        )
        await session.commit()

        if user.is_blocked:
            # Silently ignore blocked users.
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ ограничён.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Доступ ограничён.")
            return None

        if not await _has_required_channel_subscription(data, tg_user.id):
            markup = _subscription_keyboard()
            text = (
                f"{pe('lock')} <b>Доступ к боту открыт только подписчикам канала.</b>\n\n"
                "Подпишитесь на канал и нажмите кнопку проверки."
            )
            if isinstance(event, CallbackQuery):
                try:
                    await event.message.edit_text(text, reply_markup=markup)
                except Exception:  # noqa: BLE001
                    await event.message.answer(text, reply_markup=markup)
                await event.answer("Сначала подпишитесь на канал.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
            return None

        data["user"] = user
        return await handler(event, data)


async def _has_required_channel_subscription(data: dict[str, Any], user_id: int) -> bool:
    if not settings.required_channel_id:
        return True
    if settings.is_admin(user_id):
        return True
    bot = data.get("bot")
    if bot is None:
        return True
    try:
        member = await bot.get_chat_member(settings.required_channel_id, user_id)
    except TelegramBadRequest:
        return False
    return member.status in {"creator", "administrator", "member"}


def _subscription_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if settings.required_channel_url:
        rows.append([make_url_button("📢 Подписаться", settings.required_channel_url)])
    rows.append([make_button("✅ Проверить подписку", "menu:open", "success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
