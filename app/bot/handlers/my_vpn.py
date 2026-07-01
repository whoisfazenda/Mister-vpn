"""My VPN section: card, subscription link, freeze/unfreeze."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client
from app.bot.handlers._errors import friendly_error
from app.bot.keyboards.factory import inline_keyboard
from app.bot.premium_emoji import pe
from app.bot.screens import replace_with_text_screen
from app.bot.keyboards.menus import (
    my_vpn_keyboard,
    no_subscription_keyboard,
    subscription_link_keyboard,
)
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.models.subscription import VPNSubscription
from app.repositories.subscriptions import SubscriptionRepository
from app.services.subscriptions import SubscriptionService

logger = get_logger(__name__)
router = Router(name="myvpn")


async def _load_sub(session: AsyncSession, user: User):
    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
    return service, sub


async def _load_sub_by_uuid(
    session: AsyncSession,
    user: User,
    subscription_uuid: str | None,
) -> tuple[SubscriptionService, VPNSubscription | None]:
    service = SubscriptionService(session, get_client())
    if subscription_uuid:
        sub = await SubscriptionRepository(session).get_by_uuid(subscription_uuid)
        if sub and sub.user_id == user.id:
            return service, sub
        return service, None
    return await _load_sub(session, user)


def _freeze_uuid(callback: CallbackQuery) -> str | None:
    parts = (callback.data or "").split(":", 2)
    return parts[2] if len(parts) == 3 else None


@router.callback_query(F.data == "myvpn:open")
async def open_my_vpn(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service, sub = await _load_sub(session, user)
    if sub is None:
        await replace_with_text_screen(
            callback,
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

    await replace_with_text_screen(
        callback,
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
    await replace_with_text_screen(
        callback,
        texts.subscription_link(sub.subscription_url),
        reply_markup=subscription_link_keyboard(sub.subscription_url),
    )
    await callback.answer()


# ── freeze / unfreeze ────────────────────────────────────────
@router.callback_query(F.data.startswith("freeze:confirm"))
async def confirm_freeze(callback: CallbackQuery) -> None:
    subscription_uuid = _freeze_uuid(callback)
    suffix = f":{subscription_uuid}" if subscription_uuid else ""
    back_callback = "profile:subs" if subscription_uuid else "myvpn:open"
    rows = [
        [("✅ Да, заморозить", f"freeze:do{suffix}", "danger")],
        [("⬅️ Отмена", back_callback)],
    ]
    await replace_with_text_screen(
        callback,
        "⏸ <b>Заморозить подписку?</b>\n\n"
        "Заморозка временно останавливает VPN-доступ по этой подписке. "
        "Пока подписка заморожена, подключение не работает, но срок действия сохраняется "
        "и продолжит идти после разморозки.\n\n"
        "Используйте это, если уезжаете или временно не пользуетесь VPN.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("freeze:do"))
async def do_freeze(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subscription_uuid = _freeze_uuid(callback)
    service, sub = await _load_sub_by_uuid(session, user, subscription_uuid)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    try:
        await service.freeze(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    await callback.answer("Подписка заморожена ❄️")
    if subscription_uuid:
        await replace_with_text_screen(
            callback,
            f"{pe('frozen')} <b>Подписка заморожена.</b>\n\n"
            "VPN по этой подписке временно остановлен. Чтобы снова пользоваться доступом, нажмите «Разморозить» в карточке подписки.",
            reply_markup=inline_keyboard([[("⬅️ К подпискам", "profile:subs")]]),
        )
    else:
        await open_my_vpn(callback, session, user)


@router.callback_query(F.data.startswith("freeze:unfreeze"))
async def do_unfreeze(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subscription_uuid = _freeze_uuid(callback)
    service, sub = await _load_sub_by_uuid(session, user, subscription_uuid)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    try:
        await service.unfreeze(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    await callback.answer("Подписка разморожена ▶️")
    if subscription_uuid:
        await replace_with_text_screen(
            callback,
            f"{pe('active')} <b>Подписка разморожена.</b>\n\n"
            "VPN снова активен. Можно открыть карточку подписки и пользоваться доступом.",
            reply_markup=inline_keyboard([[("⬅️ К подпискам", "profile:subs")]]),
        )
    else:
        await open_my_vpn(callback, session, user)
