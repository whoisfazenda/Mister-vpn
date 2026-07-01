"""Renew flow: same-plan renew and custom-days renew. Both go through payment."""
from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client, get_payments
from app.bot.handlers._errors import friendly_error
from app.bot.keyboards.factory import inline_keyboard, make_button, make_url_button
from app.bot.premium_emoji import pe
from app.bot.states import CustomRenewStates
from app.core.config import settings
from app.core.enums import OrderType
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.models.subscription import VPNSubscription
from app.repositories.subscriptions import SubscriptionRepository
from app.services.orders import OrderService
from app.services.plans import PlanService
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import format_days, format_price
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = get_logger(__name__)
router = Router(name="renew")

MAX_CUSTOM_DAYS = 365
MIN_CUSTOM_DAYS = 3


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


def _renew_suffix(callback: CallbackQuery) -> str | None:
    parts = (callback.data or "").split(":", 2)
    return parts[2] if len(parts) == 3 else None


@router.callback_query(F.data.startswith("renew:menu"))
async def renew_menu(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subscription_uuid = _renew_suffix(callback)
    sub = await _load_sub(session, user, subscription_uuid)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if sub.is_trial:
        await callback.message.edit_text(
            f"{pe('gift')} <b>Пробную подписку продлить нельзя.</b>\n\n"
            "Чтобы продолжить пользоваться VPN после теста, выберите основной тариф.",
            reply_markup=inline_keyboard(
                [
                    [("🛒 Купить VPN", "buy:list", "success")],
                    [("⬅️ В профиль", "profile:open")],
                ]
            ),
        )
        await callback.answer()
        return

    plan_price = None
    if sub.plan_uuid:
        plan = await PlanService(session, get_client()).get_plan(sub.plan_uuid)
        if plan and plan.retail_price is not None:
            plan_price = format_price(float(plan.retail_price), plan.currency)

    text = [f"{pe('renew')} <b>Продление подписки</b>", ""]
    text.append(f"Тариф: <b>{texts.escape(sub.plan_name or 'VPN')}</b>")
    if plan_price:
        text.append(f"Продление по текущему тарифу: <b>{plan_price}</b>")
    text.append("Выберите вариант продления:")

    suffix = f":{sub.subscription_uuid}"
    rows = [
        [("♻️ Продлить текущий тариф", f"renew:same{suffix}", "success")],
        [("📆 Продлить на N дней", f"renew:custom{suffix}", "primary")],
        [("⬅️ К подпискам", "profile:subs")],
    ]
    await callback.message.edit_text("\n".join(text), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:same"))
async def renew_same(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subscription_uuid = _renew_suffix(callback)
    sub = await _load_sub(session, user, subscription_uuid)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if sub.is_trial:
        await callback.answer("Пробную подписку нельзя продлить. Выберите основной тариф.", show_alert=True)
        return

    amount = Decimal("0")
    currency = settings.currency
    if sub.plan_uuid:
        plan = await PlanService(session, get_client()).get_plan(sub.plan_uuid)
        if plan and plan.retail_price is not None:
            amount = Decimal(str(plan.retail_price))
            currency = plan.currency

    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_action_order(
        user.id, OrderType.RENEW, sub.subscription_uuid, amount=amount, currency=currency
    )
    url = await order_service.start_payment(order)
    await _payment_screen(
        callback, order.order_uuid, url,
        f"{pe('renew')} Продление текущего тарифа\n\nК оплате: <b>{format_price(float(amount), currency)}</b>",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("renew:custom"))
async def renew_custom_start(callback: CallbackQuery, state: FSMContext) -> None:
    subscription_uuid = _renew_suffix(callback)
    await state.update_data(renew_subscription_uuid=subscription_uuid)
    await state.set_state(CustomRenewStates.waiting_days)
    await callback.message.edit_text(
        f"{pe('calendar')} <b>Продление на N дней</b>\n\n"
        f"Отправьте число дней (от {MIN_CUSTOM_DAYS} до {MAX_CUSTOM_DAYS}).",
        reply_markup=inline_keyboard([[("⬅️ Отмена", "profile:subs")]]),
    )
    await callback.answer()


@router.message(CustomRenewStates.waiting_days)
async def renew_custom_days(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите целое число дней.")
        return
    days = int(raw)
    if not (MIN_CUSTOM_DAYS <= days <= MAX_CUSTOM_DAYS):
        await message.answer(f"Число дней должно быть от {MIN_CUSTOM_DAYS} до {MAX_CUSTOM_DAYS}.")
        return
    data = await state.get_data()
    await state.clear()
    subscription_uuid = data.get("renew_subscription_uuid")
    sub = await _load_sub(session, user, str(subscription_uuid) if subscription_uuid else None)
    if sub is None:
        await message.answer(texts.ERROR_NOT_FOUND)
        return
    if sub.is_trial:
        await message.answer("Пробную подписку нельзя продлить. Выберите основной тариф.")
        return

    # Price per day derived from current plan (best-effort).
    amount = Decimal("0")
    currency = settings.currency
    if sub.plan_uuid:
        plan = await PlanService(session, get_client()).get_plan(sub.plan_uuid)
        if plan and plan.retail_price is not None and plan.duration_days:
            per_day = Decimal(str(plan.retail_price)) / Decimal(plan.duration_days)
            amount = (per_day * days).quantize(Decimal("0.01"))
            currency = plan.currency

    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_action_order(
        user.id, OrderType.RENEW_CUSTOM, sub.subscription_uuid,
        amount=amount, currency=currency, extra={"days": days},
    )
    url = await order_service.start_payment(order)

    rows: list[list[InlineKeyboardButton]] = [
        [make_url_button("👛 Перейти к оплате", url)],
        [make_button("✅ Проверить оплату", f"pay:check:{order.order_uuid}", "success")],
    ]
    if settings.dev_mode:
        rows.append([make_button("🧪 [DEV] Отметить оплаченным", f"pay:devpaid:{order.order_uuid}", "primary")])
    rows.append([make_button("❌ Отменить", f"pay:cancel:{order.order_uuid}", "danger")])
    await message.answer(
        f"📆 Продление на {format_days(days)}\n\n"
        f"К оплате: <b>{format_price(float(amount), currency)}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _payment_screen(callback: CallbackQuery, order_uuid: str, url: str, text: str) -> None:
    rows: list[list[InlineKeyboardButton]] = [
        [make_url_button("👛 Перейти к оплате", url)],
        [make_button("✅ Проверить оплату", f"pay:check:{order_uuid}", "success")],
    ]
    if settings.dev_mode:
        rows.append([make_button("🧪 [DEV] Отметить оплаченным", f"pay:devpaid:{order_uuid}", "primary")])
    rows.append([make_button("❌ Отменить", f"pay:cancel:{order_uuid}", "danger")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
