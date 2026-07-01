"""Traffic top-up flow (only for limited plans). Pay, then /subs/traffic."""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client, get_payments
from app.bot.keyboards.factory import inline_keyboard, make_button, make_url_button
from app.bot.premium_emoji import pe
from app.core.config import settings
from app.core.enums import OrderType
from app.db.models.user import User
from app.db.models.subscription import VPNSubscription
from app.repositories.subscriptions import SubscriptionRepository
from app.services.orders import OrderService
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import format_price
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router(name="traffic")

# Offered top-up packs: GB → price. AdaptGroup charges the integration when the
# operation is executed; the user-facing retail price is configured locally.
TRAFFIC_PACKS = [10, 30, 50, 100]


async def _load_sub(
    session: AsyncSession,
    user: User,
    subscription_uuid: str | None = None,
) -> VPNSubscription | None:
    if subscription_uuid:
        sub = await SubscriptionRepository(session).get_by_uuid(subscription_uuid)
        if sub and sub.user_id == user.id:
            return sub
        return None
    return await SubscriptionService(session, get_client()).get_user_subscription(user.id)


def _traffic_menu_uuid(callback: CallbackQuery) -> str | None:
    parts = (callback.data or "").split(":", 2)
    return parts[2] if len(parts) == 3 else None


@router.callback_query(F.data.startswith("traffic:menu"))
async def traffic_menu(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subscription_uuid = _traffic_menu_uuid(callback)
    sub = await _load_sub(session, user, subscription_uuid)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if sub.is_unlimited_traffic:
        await callback.answer("На вашем тарифе трафик безлимитный.", show_alert=True)
        return

    rows = []
    for gb in TRAFFIC_PACKS:
        price = format_price(float(settings.traffic_price_per_gb * gb), settings.currency)
        rows.append([(f"⚡ +{gb} ГБ · {price}", f"traffic:buy:{sub.subscription_uuid}:{gb}", "primary")])
    rows.append([("⬅️ К подпискам", "profile:subs")])
    await callback.message.edit_text(
        f"{pe('traffic')} <b>Докупить трафик</b>\n\n"
        f"Подписка: <b>{texts.escape(sub.plan_name or 'VPN')}</b>\n"
        "Выберите объём:",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("traffic:buy:"))
async def traffic_buy(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) == 3:
        subscription_uuid = None
        raw = parts[2]
    elif len(parts) == 4:
        subscription_uuid = parts[2]
        raw = parts[3]
    else:
        await callback.answer(texts.ERROR_GENERIC, show_alert=True)
        return
    if not raw.isdigit() or int(raw) not in TRAFFIC_PACKS:
        await callback.answer(texts.ERROR_GENERIC, show_alert=True)
        return
    gb = int(raw)

    sub = await _load_sub(session, user, subscription_uuid)
    if sub is None or sub.is_unlimited_traffic:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return

    amount = Decimal(settings.traffic_price_per_gb) * gb
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_action_order(
        user.id, OrderType.TRAFFIC, sub.subscription_uuid,
        amount=amount, currency=settings.currency, extra={"amount_gb": gb},
    )
    url = await order_service.start_payment(order)

    rows: list[list[InlineKeyboardButton]] = [
        [make_url_button("👛 Перейти к оплате", url)],
        [make_button("✅ Проверить оплату", f"pay:check:{order.order_uuid}", "success")],
    ]
    if settings.dev_mode:
        rows.append([make_button("🧪 [DEV] Отметить оплаченным", f"pay:devpaid:{order.order_uuid}", "primary")])
    rows.append([make_button("❌ Отменить", f"pay:cancel:{order.order_uuid}", "danger")])
    await callback.message.edit_text(
        f"{pe('traffic')} Докупить <b>{gb} ГБ</b>\n\nК оплате: <b>{format_price(float(amount), settings.currency)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()
