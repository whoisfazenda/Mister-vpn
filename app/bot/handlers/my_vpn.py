"""My VPN section: card, subscription link, freeze/unfreeze."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client
from app.bot.handlers._errors import friendly_error
from app.bot.keyboards.factory import inline_keyboard
from app.bot.keyboards.menus import (
    my_vpn_keyboard,
    no_subscription_keyboard,
    subscription_link_keyboard,
)
from app.core.logging import get_logger
from app.db.models.user import User
from app.services.subscriptions import SubscriptionService

logger = get_logger(__name__)
router = Router(name="myvpn")


async def _load_sub(session: AsyncSession, user: User):
    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
    return service, sub


@router.callback_query(F.data == "myvpn:open")
async def open_my_vpn(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service, sub = await _load_sub(session, user)
    if sub is None:
        await callback.message.edit_text(
            texts.NO_SUBSCRIPTION, reply_markup=no_subscription_keyboard()
        )
        await callback.answer()
        return

    devices_used: int | None = None
    try:
        await service.refresh_from_api(sub)
        devices = await service.get_devices(sub)
        devices_used = len(devices)
    except Exception as exc:  # noqa: BLE001 — show cached data
        logger.info("Could not refresh subscription %s: %s", sub.subscription_uuid, exc)

    await callback.message.edit_text(
        texts.subscription_card(sub, devices_used),
        reply_markup=my_vpn_keyboard(sub),
    )
    await callback.answer()


@router.callback_query(F.data == "myvpn:link")
async def get_link(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    _, sub = await _load_sub(session, user)
    if sub is None or not sub.subscription_url:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    await callback.message.edit_text(
        texts.subscription_link(sub.subscription_url),
        reply_markup=subscription_link_keyboard(sub.subscription_url),
    )
    await callback.answer()


# ── freeze / unfreeze ────────────────────────────────────────
@router.callback_query(F.data == "freeze:confirm")
async def confirm_freeze(callback: CallbackQuery) -> None:
    rows = [
        [("✅ Да, заморозить", "freeze:do", "danger")],
        [("⬅️ Отмена", "myvpn:open")],
    ]
    await callback.message.edit_text(
        "⏸ <b>Заморозить подписку?</b>\n\n"
        "Пока подписка заморожена, VPN не работает. "
        "Срок действия сохраняется и продолжится после разморозки.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data == "freeze:do")
async def do_freeze(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service, sub = await _load_sub(session, user)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    try:
        await service.freeze(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    await callback.answer("Подписка заморожена ❄️")
    await open_my_vpn(callback, session, user)


@router.callback_query(F.data == "freeze:unfreeze")
async def do_unfreeze(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service, sub = await _load_sub(session, user)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    try:
        await service.unfreeze(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    await callback.answer("Подписка разморожена ▶️")
    await open_my_vpn(callback, session, user)
