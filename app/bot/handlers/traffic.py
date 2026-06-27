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
from app.services.orders import OrderService
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import format_price
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router(name="traffic")

# Offered top-up packs: GB → price. AdaptGroup charges the integration when the
# operation is executed; the user-facing retail price is configured locally.
TRAFFIC_PACKS = [10, 30, 50, 100]


@router.callback_query(F.data == "traffic:menu")
async def traffic_menu(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if sub.is_unlimited_traffic:
        await callback.answer("На вашем тарифе трафик безлимитный.", show_alert=True)
        return

    rows = []
    for gb in TRAFFIC_PACKS:
        price = format_price(float(settings.traffic_price_per_gb * gb), settings.currency)
        rows.append([(f"⚡ +{gb} ГБ · {price}", f"traffic:buy:{gb}", "primary")])
    rows.append([("⬅️ В профиль", "profile:open")])
    await callback.message.edit_text(
        f"{pe('traffic')} <b>Докупить трафик</b>\n\nВыберите объём:",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("traffic:buy:"))
async def traffic_buy(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    raw = callback.data.split(":", 2)[2]
    if not raw.isdigit() or int(raw) not in TRAFFIC_PACKS:
        await callback.answer(texts.ERROR_GENERIC, show_alert=True)
        return
    gb = int(raw)

    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
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
        [make_url_button("💳 Перейти к оплате", url)],
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
