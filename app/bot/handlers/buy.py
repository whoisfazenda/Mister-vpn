"""Buy flow: list plans → plan card → create order → pay → provision."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client, get_payments
from app.bot.handlers._errors import friendly_error, needs_admin_alert
from app.bot.keyboards.factory import inline_keyboard, make_url_button
from app.bot.keyboards.menus import back_to_menu
from app.bot.premium_emoji import pe
from app.bot.screens import BUY_IMAGE, replace_with_photo_screen, replace_with_text_screen
from app.core.config import settings
from app.core.enums import OrderType
from app.core.logging import get_logger
from app.core.plan_periods import valid_period_key
from app.db.models.user import User
from app.services.notifications import NotificationService
from app.services.orders import OrderService
from app.services.plan_periods import PlanPeriodService
from app.services.plans import PlanService
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = get_logger(__name__)
router = Router(name="buy")


@router.callback_query(F.data == "buy:list")
async def list_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    service = PlanService(session, get_client())
    try:
        plans = await service.get_purchasable_plans()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load plans: %s", exc)
        plans = await service.repo.list_active(include_trial=False, public_only=True)

    if not plans:
        await replace_with_photo_screen(
            callback,
            BUY_IMAGE,
            texts.BUY_EMPTY,
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return

    periods = [p for p in await PlanPeriodService(session).list_periods() if p.enabled]
    rows = [
        [(f"{period.emoji} {period.label}", f"buy:period:{period.key}", period.style)]
        for period in periods
    ]
    if not rows:
        await replace_with_photo_screen(
            callback,
            BUY_IMAGE,
            f"{pe('buy')} <b>Покупка временно недоступна</b>\n\n"
            "Администратор пока не включил сроки подписки.",
            reply_markup=back_to_menu(),
        )
        await callback.answer()
        return
    rows.append([("⬅️ В меню", "menu:open")])
    await replace_with_photo_screen(
        callback,
        BUY_IMAGE,
        f"{pe('buy')} <b>Выберите срок подписки</b>\n\nПосле этого покажу тарифы на выбранный срок.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:period:"))
async def list_period_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    period = callback.data.split(":", 2)[2]
    if not valid_period_key(period):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    service = PlanService(session, get_client())
    period_view = await PlanPeriodService(session).get_period(period)
    if not period_view.enabled:
        await callback.answer("Этот срок временно недоступен.", show_alert=True)
        return
    plans = await service.repo.list_active_by_period(
        period,
        include_trial=False,
        public_only=True,
    )
    if not plans:
        await callback.answer("В этой категории пока нет тарифов.", show_alert=True)
        return
    rows = [
        [
            (
                texts.plan_button_label(p),
                f"buy:plan:{p.plan_uuid}",
                getattr(p, "button_style", None) or "primary",
            )
        ]
        for p in plans
    ]
    rows.append([("⬅️ К срокам", "buy:list")])
    await replace_with_photo_screen(
        callback,
        BUY_IMAGE,
        f"{pe('buy')} <b>{period_view.label}</b>\n\nВыберите тариф:",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:plan:"))
async def show_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    service = PlanService(session, get_client())
    plan = await service.get_plan(plan_uuid)
    if plan is None or not plan.is_active or plan.is_trial:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    rows = [
        [("💰 Оплатить с баланса", f"buy:balance:{plan.plan_uuid}", "success")],
        [("👛 Оплатить напрямую", f"buy:order:{plan.plan_uuid}", "primary")],
        [("⬅️ К тарифам", f"buy:period:{plan.period_group}" if plan.period_group else "buy:list")],
    ]
    await replace_with_text_screen(callback, texts.plan_card(plan), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("buy:order:"))
async def create_order(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    service = PlanService(session, get_client())
    plan = await service.get_plan(plan_uuid)
    if plan is None or not plan.is_active or plan.is_trial:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return

    order_service = OrderService(session, get_client(), get_payments())
    try:
        order = await order_service.create_new_subscription_order(user.id, plan_uuid)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await render_payment_method_choice(
        callback,
        order.order_uuid,
        texts.order_summary(plan),
        back_callback=f"buy:plan:{plan.plan_uuid}",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buy:balance:"))
async def buy_from_balance(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    service = PlanService(session, get_client())
    plan = await service.get_plan(plan_uuid)
    if plan is None or not plan.is_active or plan.is_trial:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if plan.retail_price is None:
        await callback.answer("У тарифа пока нет цены. Синхронизируйте тарифы.", show_alert=True)
        return

    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_new_subscription_order(user.id, plan_uuid)
    enough = await order_service.pay_from_balance(order)
    if not enough:
        need = float(plan.retail_price) - float(user.balance or 0)
        from app.bot.keyboards.factory import make_button

        rows = [
            [make_button(f"💳 Пополнить на {need:.0f} {plan.currency}", "balance:topup", "success")],
            [make_button("⬅️ К тарифу", f"buy:plan:{plan.plan_uuid}")],
        ]
        await replace_with_text_screen(
            callback,
            f"{pe('balance')} <b>Недостаточно средств на балансе</b>\n\n"
            f"Баланс: <b>{float(user.balance or 0):.2f} {user.balance_currency}</b>\n"
            f"Нужно: <b>{float(plan.retail_price):.2f} {plan.currency}</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        await callback.answer()
        return

    await _provision_and_report(callback, order_service, order, user)


async def render_payment_method_choice(
    target,
    order_uuid: str,
    text: str,
    *,
    back_callback: str | None = None,
    include_yookassa_sbp: bool = False,
) -> None:
    from app.bot.keyboards.factory import make_button

    rows: list[list[InlineKeyboardButton]] = [
        [make_button("👛 Карта / СБП", f"pay:start:yookassa_all:{order_uuid}", "primary")],
        [make_button("💎 Криптовалютой", f"pay:start:crypto:{order_uuid}", "success")],
        [make_button("🚀 xRocket", f"pay:start:xrocket:{order_uuid}", "success")],
        [make_button("🤖 CryptoBot", f"pay:start:cryptobot:{order_uuid}", "success")],
        [make_button("❌ Отменить", f"pay:cancel:{order_uuid}", "danger")],
    ]
    if back_callback:
        rows.append([make_button("⬅️ Назад", back_callback)])
    message_text = text + "\n\nВыберите способ оплаты:"
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, CallbackQuery):
        await replace_with_text_screen(target, message_text, reply_markup=markup)
    else:
        await target.answer(message_text, reply_markup=markup)


async def _render_payment_screen(
    callback,
    order,
    confirmation_url,
    *,
    method_label: str = "",
) -> None:
    rows: list[list[InlineKeyboardButton]] = []
    from app.bot.keyboards.factory import make_button

    if method_label:
        pay_label = f"👛 Перейти к оплате"
    else:
        pay_label = "👛 Перейти к оплате"
    rows.append([make_url_button(pay_label, confirmation_url)])
    rows.append([make_button("\u2705 \u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043e\u043f\u043b\u0430\u0442\u0443", f"pay:check:{order.order_uuid}", "success")])
    if settings.dev_mode:
        rows.append(
            [make_button("\U0001f9ea [DEV] \u041e\u0442\u043c\u0435\u0442\u0438\u0442\u044c \u043e\u043f\u043b\u0430\u0447\u0435\u043d\u043d\u044b\u043c", f"pay:devpaid:{order.order_uuid}", "primary")]
        )
    rows.append([make_button("\u274c \u041e\u0442\u043c\u0435\u043d\u0438\u0442\u044c", f"pay:cancel:{order.order_uuid}", "danger")])

    method_line = f"\nСпособ оплаты: <b>{texts.escape(method_label)}</b>" if method_label else ""

    await replace_with_text_screen(
        callback,
        _payment_text(order) + method_line,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )

def _payment_text(order) -> str:
    if order.order_type == OrderType.BALANCE_TOPUP:
        return (
            f"{pe('balance')} <b>Пополнение баланса</b>\n\n"
            f"Сумма: <b>{float(order.amount):.2f} {order.currency}</b>\n\n"
            "После оплаты нажмите «Проверить оплату»."
        )
    if order.order_type == OrderType.NEW_SUBSCRIPTION:
        snap = order.snapshot or {}
        lines = [
            f"{pe('subs')} <b>Ваш заказ</b>",
            "",
            f"Тариф: <b>{texts.escape(snap.get('plan_name') or 'VPN')}</b>",
        ]
        if snap.get("duration_days"):
            lines.append(f"Срок: {snap['duration_days']} дн.")
        if snap.get("max_devices"):
            lines.append(f"Устройств: до {snap['max_devices']}")
        lines.extend(["", f"К оплате: <b>{float(order.amount):.2f} {order.currency}</b>"])
        return "\n".join(lines)
    return (
        f"{pe('subs')} <b>Оплата</b>\n\n"
        f"К оплате: <b>{float(order.amount):.2f} {order.currency}</b>\n\n"
        "После оплаты нажмите «Проверить оплату»."
    )


def _provider_for_payment_method(method: str) -> str:
    if method in {"yookassa_all", "yookassa_card", "yookassa_sbp"}:
        return "yookassa"
    if method in {"crypto", "xrocket", "cryptobot"}:
        return "rollypay"
    return settings.payment_provider


def _provider_payment_method(method: str) -> str | None:
    mapping = {
        "yookassa_all": None,
        "yookassa_card": "bank_card",
        "yookassa_sbp": "sbp",
        "crypto": "crypto",
        "xrocket": "xrocket",
        "cryptobot": "cryptobot",
    }
    return mapping.get(method)


def _payment_method_label(method: str) -> str:
    labels = {
        "yookassa_all": "Карта / СБП / ЮMoney",
        "yookassa_card": "Картой через ЮKassa",
        "yookassa_sbp": "СБП через ЮKassa",
        "crypto": "Криптовалютой через RollyPay",
        "xrocket": "xRocket через RollyPay",
        "cryptobot": "CryptoBot через RollyPay",
    }
    return labels.get(method, "Оплата")


# ── payment actions ──────────────────────────────────────────
@router.callback_query(F.data.startswith("pay:start:"))
async def start_selected_payment(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    _, _, method, order_uuid = callback.data.split(":", 3)
    from app.services.payments.factory import get_payment_provider

    await callback.answer()
    payment_provider = get_payment_provider(_provider_for_payment_method(method))
    order_service = OrderService(session, get_client(), payment_provider)
    order = await order_service.orders.get_by_uuid(order_uuid)
    if order is None or order.user_id != user.id:
        await replace_with_text_screen(callback, texts.ERROR_NOT_FOUND, reply_markup=back_to_menu())
        return
    order.payment_provider = payment_provider.name
    payment_method = _provider_payment_method(method)
    method_label = _payment_method_label(method)
    try:
        confirmation_url = await order_service.start_payment(order, payment_method=payment_method)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Payment creation failed: %s", exc)
        await replace_with_text_screen(callback, friendly_error(exc), reply_markup=back_to_menu())
        return
    await _render_payment_screen(
        callback,
        order,
        confirmation_url,
        method_label=method_label,
    )


@router.callback_query(F.data.startswith("pay:check:"))
async def check_payment(callback: CallbackQuery, session: AsyncSession, user: User, bot=None) -> None:
    order_uuid = callback.data.split(":", 2)[2]
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.orders.get_by_uuid(order_uuid)
    if order is None or order.user_id != user.id:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return

    try:
        paid = await order_service.check_and_mark_paid(order)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Payment check failed: %s", exc)
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    if not paid:
        await callback.answer(texts.ERROR_PAYMENT_PENDING, show_alert=True)
        return

    await _provision_and_report(callback, order_service, order, user)


@router.callback_query(F.data.startswith("pay:devpaid:"))
async def dev_mark_paid(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if not settings.dev_mode:
        await callback.answer("Недоступно.", show_alert=True)
        return
    order_uuid = callback.data.split(":", 2)[2]
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.orders.get_by_uuid(order_uuid)
    if order is None or order.user_id != user.id:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    await order_service.dev_mark_paid(order)
    await _provision_and_report(callback, order_service, order, user)


@router.callback_query(F.data.startswith("pay:cancel:"))
async def cancel_order(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    from app.core.enums import OrderStatus, OrderType

    order_uuid = callback.data.split(":", 2)[2]
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.orders.get_by_uuid(order_uuid)
    if order is None or order.user_id != user.id:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.CANCELLED
        await session.commit()
    if order.order_type == OrderType.BALANCE_TOPUP:
        await replace_with_text_screen(
            callback,
            f"{pe('cross')} <b>Пополнение баланса отменено.</b>",
            reply_markup=inline_keyboard(
                [
                    [("💳 Пополнить баланс", "balance:topup", "success")],
                    [("👤 В профиль", "profile:open", "primary")],
                ]
            ),
        )
    else:
        await replace_with_text_screen(
            callback,
            f"{pe('cross')} <b>Заказ отменён.</b>",
            reply_markup=inline_keyboard(
                [
                    [("🛒 К тарифам", "buy:list", "primary")],
                    [("👤 В профиль", "profile:open")],
                ]
            ),
        )
    await callback.answer()


async def _provision_and_report(callback, order_service: OrderService, order, user: User) -> None:
    """Provision a paid order and render the result (idempotent)."""
    from app.core.enums import OrderType

    # Reload user relationship for external_user_id (telegram_id).
    order.user  # ensure loaded via selectin
    outcome = await order_service.provision(order)

    if outcome.already_done or outcome.provisioned:
        if order.order_type == OrderType.BALANCE_TOPUP:
            await replace_with_text_screen(
                callback,
                f"{pe('check')} <b>Баланс пополнен!</b>\n\n"
                f"Текущий баланс: <b>{float(order.user.balance or 0):.2f} {order.user.balance_currency}</b>",
                reply_markup=inline_keyboard(
                    [
                        [("👤 В профиль", "profile:open", "primary")],
                        [("🛒 Купить VPN", "buy:list", "success")],
                    ]
                ),
            )
            await callback.answer("Баланс пополнен ✅")
            return
        sub = outcome.subscription
        from app.bot.keyboards.menus import subscription_link_keyboard

        if sub is not None and order.order_type == OrderType.NEW_SUBSCRIPTION and sub.subscription_url:
            text = (
                f"{pe('sparkles')} <b>Подписка оформлена!</b>\n\n"
                + texts.subscription_link(sub.subscription_url)
            )
            await replace_with_text_screen(
                callback,
                text, reply_markup=subscription_link_keyboard(sub.subscription_url)
            )
        else:
            from app.bot.keyboards.menus import main_menu

            await replace_with_text_screen(
                callback,
                f"{pe('check')} <b>Готово!</b> Операция выполнена.", reply_markup=main_menu()
            )
        await callback.answer("Готово ✅")
        return

    # Provisioning failed.
    await _report_provision_failure(callback, order_service, outcome, user)


async def _report_provision_failure(callback, order_service, outcome, user) -> None:
    from app.bot.keyboards.menus import support_keyboard

    # Alert admins for critical issues.
    try:
        notifier = NotificationService(callback.bot)
        await notifier.alert_admins(
            f"Сбой выдачи VPN по заказу {outcome.order.order_uuid}\n"
            f"Пользователь: {user.telegram_id}\n"
            f"Статус: {outcome.order.status}\n"
            f"needs_manual_review: {outcome.order.needs_manual_review}"
        )
    except Exception:  # noqa: BLE001
        pass

    err_text = outcome.error or ""
    if outcome.order.needs_manual_review or "NETWORK/UNKNOWN" in err_text:
        # Surface a careful message; admin review required.
        await replace_with_text_screen(
            callback,
            f"{pe('warning')} <b>Оплата получена, но выдача задержалась.</b>\n\n"
            "Мы уже проверяем ваш заказ вручную и активируем VPN в ближайшее время. "
            "Повторно платить не нужно.",
            reply_markup=support_keyboard(),
        )
        await callback.answer()
        return

    await replace_with_text_screen(
        callback,
        f"{pe('warning')} <b>Оплата получена, но активировать VPN не удалось.</b>\n\n"
        "Деньги не потеряны. Попробуйте ещё раз или напишите в поддержку — мы поможем.",
        reply_markup=support_keyboard(),
    )
    await callback.answer()
