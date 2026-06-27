"""Upgrade flow: choose a higher plan, pay, then /subs/upgrade."""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client, get_payments
from app.bot.keyboards.factory import inline_keyboard, make_button, make_url_button
from app.core.config import settings
from app.core.enums import OrderType
from app.db.models.user import User
from app.services.orders import OrderService
from app.services.plans import PlanService
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import format_price
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

router = Router(name="upgrade")


@router.callback_query(F.data == "upgrade:menu")
async def upgrade_menu(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    sub_service = SubscriptionService(session, get_client())
    sub = await sub_service.get_user_subscription(user.id)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return

    plan_service = PlanService(session, get_client())
    try:
        plans = await plan_service.get_purchasable_plans()
    except Exception:  # noqa: BLE001
        plans = await plan_service.repo.list_active(include_trial=False, public_only=True)

    # Offer plans other than the current one.
    options = [p for p in plans if p.plan_uuid != sub.plan_uuid]
    if not options:
        await callback.answer("Нет доступных тарифов для перехода.", show_alert=True)
        return

    rows = [
        [(texts.plan_button_label(p), f"upgrade:plan:{p.plan_uuid}", "primary")]
        for p in options
    ]
    rows.append([("⬅️ В профиль", "profile:open")])
    await callback.message.edit_text(
        "🚀 <b>Улучшение тарифа</b>\n\nВыберите новый тариф:",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("upgrade:plan:"))
async def upgrade_plan(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    sub_service = SubscriptionService(session, get_client())
    sub = await sub_service.get_user_subscription(user.id)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    plan = await PlanService(session, get_client()).get_plan(plan_uuid)
    if plan is None or not plan.is_active or plan.is_trial:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return

    amount = Decimal(str(plan.retail_price)) if plan.retail_price is not None else Decimal("0")
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_action_order(
        user.id, OrderType.UPGRADE, sub.subscription_uuid,
        amount=amount, currency=plan.currency, extra={"plan_uuid": plan.plan_uuid},
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
        f"🚀 Переход на тариф <b>{texts.escape(plan.name)}</b>\n\n"
        f"К оплате: <b>{format_price(float(amount), plan.currency)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()
