"""Admin panel: stats, recent orders, user lookup, retry provisioning,
manual dev payment confirmation, plan sync, integration status, broadcast."""
from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts as bot_texts
from app.bot.deps import get_client, get_payments
from app.bot.filters.admin import IsAdmin
from app.bot.keyboards.factory import inline_keyboard
from app.bot.premium_emoji import EMOJI_IDS
from app.bot.screens import replace_with_text_screen
from app.bot.states import AdminStates
from app.core.config import settings
from app.core.enums import OrderStatus, OrderType
from app.core.logging import get_logger
from app.core.plan_periods import PLAN_PERIODS, period_label, valid_period_key
from app.core.security import mask_secret
from app.db.models.user import User
from app.repositories.orders import OrderRepository
from app.repositories.plans import PlanRepository
from app.repositories.promos import PromoRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.repositories.users import UserRepository
from app.services.orders import OrderService
from app.services.plan_periods import PlanPeriodService
from app.services.plans import PlanService
from app.utils.formatting import escape, format_date, format_price

logger = get_logger(__name__)
router = Router(name="admin")

# All handlers in this router require admin rights.
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

PLAN_BUTTON_STYLES = (
    ("primary", "🔵 Синяя"),
    ("success", "🟢 Зеленая"),
    ("danger", "🔴 Красная"),
)

PLAN_EMOJI_PRESETS = (
    ("auto", "🤖 Авто"),
    ("star", "⭐ Standard"),
    ("diamond", "💎 Pro"),
    ("crown", "👑 Ultra"),
    ("rocket", "🚀 Быстрый"),
    ("shield", "🛡 Защита"),
    ("sparkles", "✨ Premium"),
    ("subs", "📦 Базовый"),
)


def _admin_menu():
    return inline_keyboard(
        [
            [("📊 Статистика", "admin:stats", "primary"), ("👥 Пользователи", "admin:users")],
            [("📦 Тарифы и цены", "admin:plans", "primary"), ("🧾 Заказы", "admin:orders")],
            [("🔄 Синхр. тарифы", "admin:syncplans", "primary"), ("🔌 Интеграция", "admin:integration")],
            [("🎟 Промокоды", "admin:promos", "primary"), ("📣 Рассылка", "admin:broadcast", "danger")],
            [("⬅️ В меню", "menu:open")],
        ]
    )


@router.message(Command("admin"))
async def admin_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 <b>Админ-панель</b>", reply_markup=_admin_menu())


@router.callback_query(F.data == "admin:menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await replace_with_text_screen(callback, "🛠 <b>Админ-панель</b>", reply_markup=_admin_menu())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    users = await UserRepository(session).count()
    orders_repo = OrderRepository(session)
    total_orders = await orders_repo.count()
    completed = await orders_repo.count_by_status(OrderStatus.COMPLETED)
    pending = await orders_repo.count_by_status(OrderStatus.PENDING)
    paid = await orders_repo.count_by_status(OrderStatus.PAID)
    failed = await orders_repo.count_by_status(OrderStatus.FAILED)
    active_subs = await SubscriptionRepository(session).count_active()
    active_promos = await PromoRepository(session).count_active()

    text = (
        "📊 <b>Статистика проекта</b>\n\n"
        "👥 <b>Клиенты</b>\n"
        f"Всего пользователей: <b>{users}</b>\n"
        f"Активных VPN-подписок: <b>{active_subs}</b>\n\n"
        "🧾 <b>Заказы</b>\n"
        f"Всего: <b>{total_orders}</b>\n"
        f"В ожидании оплаты: <b>{pending}</b>\n"
        f"Оплачены, ждут выдачи: <b>{paid}</b>\n"
        f"Успешно выполнены: <b>{completed}</b>\n"
        f"С ошибкой: <b>{failed}</b>\n\n"
        "🎟 <b>Маркетинг</b>\n"
        f"Активных промокодов: <b>{active_promos}</b>"
    )
    await replace_with_text_screen(callback, 
        text, reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]])
    )
    await callback.answer()


@router.callback_query(F.data == "admin:orders")
async def admin_orders(callback: CallbackQuery, session: AsyncSession) -> None:
    orders = await OrderRepository(session).list_recent(10)
    if not orders:
        await replace_with_text_screen(callback, 
            "🧾 Заказов пока нет.", reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]])
        )
        await callback.answer()
        return

    lines = ["🧾 <b>Последние заказы</b>", ""]
    rows = []
    for o in orders:
        flag = " ⚠️" if o.needs_manual_review else ""
        lines.append(
            f"<code>{o.order_uuid[:8]}</code> · {o.order_type} · "
            f"{format_price(float(o.amount), o.currency)} · <b>{o.status}</b>{flag}"
        )
        if o.status == OrderStatus.FAILED:
            rows.append([(f"🔁 Повторить {o.order_uuid[:8]}", f"admin:retry:{o.order_uuid}", "primary")])
    rows.append([("⬅️ Назад", "admin:menu")])
    await replace_with_text_screen(callback, "\n".join(lines), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:retry:"))
async def admin_retry(callback: CallbackQuery, session: AsyncSession) -> None:
    order_uuid = callback.data.split(":", 2)[2]
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.orders.get_by_uuid(order_uuid)
    if order is None:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    if order.status not in (OrderStatus.PAID, OrderStatus.FAILED):
        await callback.answer(
            f"Повтор недоступен для статуса {order.status}.", show_alert=True
        )
        return
    outcome = await order_service.provision(order)
    if outcome.provisioned or outcome.already_done:
        await callback.answer("VPN выдан ✅", show_alert=True)
    else:
        await callback.answer(f"Не удалось: {outcome.error}", show_alert=True)
    await admin_orders(callback, session)


# ── plan storefront ─────────────────────────────────────────
@router.callback_query(F.data == "admin:plans")
async def admin_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    plans = await PlanRepository(session).list_all()
    if not plans:
        await replace_with_text_screen(callback, 
            "📦 Тарифов пока нет. Сначала синхронизируйте AdaptGroup.",
            reply_markup=inline_keyboard(
                [
                    [("🔄 Синхронизировать", "admin:syncplans", "primary")],
                    [("⚙️ Сроки витрины", "admin:periods", "primary")],
                    [("⬅️ Назад", "admin:menu")],
                ]
            ),
        )
        await callback.answer()
        return

    lines = ["📦 <b>Тарифы и цены</b>", "", "Пользователи видят только включенные тарифы."]
    rows = [[("⚙️ Сроки витрины", "admin:periods", "primary")]]
    for plan in plans:
        visible = "✅" if plan.is_public else "🚫"
        manual = "ручн." if plan.manual_price else "авто"
        name_mode = "имя ручн." if plan.manual_name else "имя Adapt"
        price = format_price(float(plan.retail_price), plan.currency) if plan.retail_price is not None else "—"
        purchase = _purchase_label(plan)
        period = period_label(plan.period_group, short=True)
        style = _plan_button_style(plan)
        emoji = _plan_button_emoji_label(plan)
        lines.append(
            f"{visible} {emoji} <b>{escape(plan.name)}</b> · {period} · {price} · {style} · {manual} · {name_mode} · закупка {purchase}"
        )
        rows.append([(f"{visible} {emoji} {plan.name[:18]}", f"admin:plan:{plan.plan_uuid}", _plan_style(plan))])
    rows.append([("⬅️ Назад", "admin:menu")])
    await replace_with_text_screen(callback, "\n".join(lines), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:plan:"))
async def admin_plan_card(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    await _render_admin_plan_card(callback, plan)
    await callback.answer()


async def _render_admin_plan_card(callback: CallbackQuery, plan) -> None:
    price = format_price(float(plan.retail_price), plan.currency) if plan.retail_price is not None else "—"
    text = (
        "📦 <b>Настройка тарифа</b>\n\n"
        f"Название: <b>{escape(plan.name)}</b>\n"
        f"Цена для клиента: <b>{price}</b>\n"
        f"Закупка AdaptGroup: <b>{_purchase_label(plan)}</b>\n"
        f"Категория срока: <b>{period_label(plan.period_group)}</b>\n"
        f"Устройства: <b>{plan.max_devices or '—'}</b>\n"
        f"Дней: <b>{plan.duration_days or '—'}</b>\n"
        f"Трафик: <b>{bot_texts.format_traffic(plan.traffic_limit_bytes)}</b>\n"
        f"В витрине: <b>{'да' if plan.is_public else 'нет'}</b>\n"
        f"Цена: <b>{'ручная' if plan.manual_price else 'авто'}</b>\n"
        f"Название: <b>{'ручное' if plan.manual_name else 'из AdaptGroup'}</b>\n"
        f"Цвет кнопки: <b>{_plan_button_style(plan)}</b>\n"
        f"Эмодзи кнопки: <b>{_plan_button_emoji_label(plan)}</b>\n\n"
        "<b>Как увидит клиент:</b>\n"
        f"<code>{escape(bot_texts.plan_button_label(plan))}</code>\n\n"
        f"{bot_texts.plan_card(plan)}"
    )
    rows = [
        [("✅ Показать" if not plan.is_public else "🚫 Скрыть", f"admin:plantoggle:{plan.plan_uuid}", "primary")],
        [("💰 Задать цену", f"admin:planprice:{plan.plan_uuid}", "success")],
        [("✏️ Название тарифа", f"admin:planname:{plan.plan_uuid}", "primary")],
        [("📅 Выбрать срок", f"admin:planperiod:{plan.plan_uuid}", "primary")],
        [("🎨 Цвет кнопки", f"admin:planstyle:{plan.plan_uuid}", "primary")],
        [("✨ Эмодзи кнопки", f"admin:planemoji:{plan.plan_uuid}", "primary")],
        [("⬅️ К тарифам", "admin:plans")],
    ]
    await replace_with_text_screen(callback, text, reply_markup=inline_keyboard(rows))


@router.callback_query(F.data.startswith("admin:planperiod:"))
async def admin_plan_period_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    rows = [
        [(period.label, f"admin:planperiodset:{plan.plan_uuid}:{period.key}", "primary")]
        for period in PLAN_PERIODS
    ]
    rows.append([("🚫 Без категории", f"admin:planperiodset:{plan.plan_uuid}:none", "danger")])
    rows.append([("⬅️ К тарифу", f"admin:plan:{plan.plan_uuid}")])
    await replace_with_text_screen(
        callback,
        "📅 <b>Категория срока</b>\n\n"
        f"Тариф: <b>{escape(plan.name)}</b>\n"
        f"Сейчас: <b>{period_label(plan.period_group)}</b>\n\n"
        "Выберите, в каком разделе покупки показывать этот тариф.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:planperiodset:"))
async def admin_plan_period_set(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, plan_uuid, period = callback.data.split(":", 3)
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    if period == "none":
        plan.period_group = None
    elif valid_period_key(period):
        plan.period_group = period
    else:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    await session.commit()
    await callback.answer("Срок сохранён ✅")
    await _render_admin_plan_card(callback, plan)


@router.callback_query(F.data.startswith("admin:planstyle:"))
async def admin_plan_style_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    rows = [
        [
            (
                f"{'✓ ' if _plan_style(plan) == style else ''}{label}",
                f"admin:planstyleset:{plan.plan_uuid}:{style}",
                style,
            )
        ]
        for style, label in PLAN_BUTTON_STYLES
    ]
    rows.append([("⬅️ К тарифу", f"admin:plan:{plan.plan_uuid}")])
    await replace_with_text_screen(
        callback,
        "🎨 <b>Цвет кнопки тарифа</b>\n\n"
        f"Тариф: <b>{escape(plan.name)}</b>\n"
        f"Сейчас: <b>{_plan_button_style(plan)}</b>\n\n"
        "Выберите цвет кнопки в витрине.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:planstyleset:"))
async def admin_plan_style_set(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, plan_uuid, style = callback.data.split(":", 3)
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    if style not in {item[0] for item in PLAN_BUTTON_STYLES}:
        await callback.answer("Цвет не найден.", show_alert=True)
        return
    plan.button_style = style
    await session.commit()
    await callback.answer("Цвет сохранён ✅")
    await _render_admin_plan_card(callback, plan)


@router.callback_query(F.data.startswith("admin:planemoji:"))
async def admin_plan_emoji_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    current = getattr(plan, "button_emoji_key", None) or "auto"
    rows = []
    for key, label in PLAN_EMOJI_PRESETS:
        style = "success" if key == current else "primary"
        rows.append([(f"{'✓ ' if key == current else ''}{label}", f"admin:planemojiset:{plan.plan_uuid}:{key}", style)])
    rows.append([("⬅️ К тарифу", f"admin:plan:{plan.plan_uuid}")])
    await replace_with_text_screen(
        callback,
        "✨ <b>Эмодзи кнопки тарифа</b>\n\n"
        f"Тариф: <b>{escape(plan.name)}</b>\n"
        f"Сейчас: <b>{_plan_button_emoji_label(plan)}</b>\n\n"
        "Авто подбирает иконку по названию: Standard, Pro, Ultra.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:planemojiset:"))
async def admin_plan_emoji_set(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, plan_uuid, emoji_key = callback.data.split(":", 3)
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    allowed = {item[0] for item in PLAN_EMOJI_PRESETS}
    if emoji_key not in allowed:
        await callback.answer("Эмодзи не найден.", show_alert=True)
        return
    plan.button_emoji_key = None if emoji_key == "auto" else emoji_key
    await session.commit()
    await callback.answer("Эмодзи сохранено ✅")
    await _render_admin_plan_card(callback, plan)


@router.callback_query(F.data == "admin:periods")
async def admin_periods(callback: CallbackQuery, session: AsyncSession) -> None:
    periods = await PlanPeriodService(session).list_periods()
    lines = ["⚙️ <b>Сроки витрины</b>", "", "Включенные сроки показываются в разделе покупки."]
    rows = []
    for period in periods:
        mark = "✅" if period.enabled else "🚫"
        changed = "" if period.label == period.default_label else " · своё название"
        lines.append(f"{mark} {period.emoji} <b>{escape(period.label)}</b>{changed}")
        rows.append(
            [
                (
                    f"{mark} {period.emoji} {period.label[:18]}",
                    f"admin:periodtoggle:{period.key}",
                    period.style,
                ),
                ("✏️", f"admin:periodname:{period.key}"),
            ]
        )
    rows.append([("⬅️ К тарифам", "admin:plans")])
    await replace_with_text_screen(callback, "\n".join(lines), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:periodtoggle:"))
async def admin_period_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    key = callback.data.split(":", 2)[2]
    service = PlanPeriodService(session)
    try:
        period = await service.get_period(key)
    except ValueError:
        await callback.answer("Срок не найден.", show_alert=True)
        return
    await service.set_enabled(key, not period.enabled)
    await session.commit()
    await callback.answer("Сохранено ✅")
    await admin_periods(callback, session)


@router.callback_query(F.data.startswith("admin:periodname:"))
async def admin_period_name_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    key = callback.data.split(":", 2)[2]
    try:
        period = await PlanPeriodService(session).get_period(key)
    except ValueError:
        await callback.answer("Срок не найден.", show_alert=True)
        return
    await state.update_data(period_key=key)
    await state.set_state(AdminStates.waiting_period_label)
    await replace_with_text_screen(
        callback,
        "✏️ <b>Название срока</b>\n\n"
        f"Сейчас: <b>{escape(period.label)}</b>\n\n"
        "Введите новое название кнопки, например: <code>1 месяц</code> или <code>30 дней</code>.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", "admin:periods")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_period_label)
async def admin_period_name_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    key = str(data.get("period_key") or "")
    label = (message.text or "").strip()
    if not label or len(label) > 32:
        await message.answer("Введите название от 1 до 32 символов.")
        return
    try:
        await PlanPeriodService(session).set_label(key, label)
    except ValueError:
        await state.clear()
        await message.answer("Срок не найден.", reply_markup=_admin_menu())
        return
    await session.commit()
    await state.clear()
    await message.answer("✅ Название срока сохранено.", reply_markup=_admin_menu())


@router.callback_query(F.data.startswith("admin:planname:"))
async def admin_plan_name_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    await state.update_data(plan_uuid=plan_uuid)
    await state.set_state(AdminStates.waiting_plan_name)
    await replace_with_text_screen(
        callback,
        "✏️ <b>Название тарифа</b>\n\n"
        f"Сейчас: <b>{escape(plan.name)}</b>\n\n"
        "Введите новое название, которое увидит пользователь.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", f"admin:plan:{plan_uuid}")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_plan_name)
async def admin_plan_name_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    plan_uuid = str(data.get("plan_uuid") or "")
    name = (message.text or "").strip()
    if not name or len(name) > 64:
        await message.answer("Введите название от 1 до 64 символов.")
        return
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await state.clear()
        await message.answer("Тариф не найден.", reply_markup=_admin_menu())
        return
    plan.name = name
    plan.manual_name = True
    await session.commit()
    await state.clear()
    await message.answer("✅ Название тарифа сохранено.", reply_markup=_admin_menu())


@router.callback_query(F.data.startswith("admin:plantoggle:"))
async def admin_plan_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await callback.answer("Тариф не найден.", show_alert=True)
        return
    plan.is_public = not plan.is_public
    await session.commit()
    await callback.answer("Сохранено ✅")
    await replace_with_text_screen(callback, 
        "✅ Настройка сохранена.",
        reply_markup=inline_keyboard([[("⬅️ К тарифам", "admin:plans")]]),
    )


@router.callback_query(F.data.startswith("admin:planprice:"))
async def admin_plan_price_start(callback: CallbackQuery, state: FSMContext) -> None:
    plan_uuid = callback.data.split(":", 2)[2]
    await state.update_data(plan_uuid=plan_uuid)
    await state.set_state(AdminStates.waiting_plan_price)
    await replace_with_text_screen(callback, 
        "💰 <b>Новая цена тарифа</b>\n\nВведите цену для клиента в RUB, например: <code>199</code>.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", f"admin:plan:{plan_uuid}")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_plan_price)
async def admin_plan_price_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    plan_uuid = str(data.get("plan_uuid") or "")
    raw = (message.text or "").strip().replace(",", ".")
    try:
        price = Decimal(raw).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        await message.answer("Введите число, например 199.")
        return
    if price <= 0:
        await message.answer("Цена должна быть больше нуля.")
        return
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if plan is None:
        await state.clear()
        await message.answer("Тариф не найден.", reply_markup=_admin_menu())
        return
    plan.retail_price = price
    plan.currency = settings.currency
    plan.manual_price = True
    plan.is_public = True
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ Цена сохранена: <b>{format_price(float(price), settings.currency)}</b>\n"
        "Тариф включен в витрину.",
        reply_markup=_admin_menu(),
    )


# ── user lookup ──────────────────────────────────────────────
@router.callback_query(F.data == "admin:finduser")
async def find_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_user_id)
    await replace_with_text_screen(callback, 
        "👤 Отправьте Telegram ID пользователя.",
        reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_id)
async def find_user_result(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("Введите числовой Telegram ID.")
        return
    await state.clear()
    target = await UserRepository(session).get_by_telegram_id(int(raw))
    if target is None:
        await message.answer("Пользователь не найден.", reply_markup=_admin_menu())
        return
    subs = await SubscriptionRepository(session).list_for_user(target.id)
    orders = await OrderRepository(session).list_for_user(target.id, limit=5)

    lines = [
        "👤 <b>Пользователь</b>",
        "",
        f"ID: <code>{target.telegram_id}</code>",
        f"Username: @{escape(target.username) if target.username else '—'}",
        f"Имя: {escape(target.first_name or '—')}",
        f"Роль: {target.role}",
        f"Блокировка: {'да' if target.is_blocked else 'нет'}",
        f"Регистрация: {format_date(target.created_at)}",
        "",
        f"Подписок: {len(subs)}",
    ]
    for s in subs:
        lines.append(f"• <code>{s.subscription_uuid[:12]}</code> до {format_date(s.expires_at)}")
    lines.append("")
    lines.append(f"Последние заказы: {len(orders)}")
    for o in orders:
        lines.append(f"• <code>{o.order_uuid[:8]}</code> {o.status} {format_price(float(o.amount), o.currency)}")

    await message.answer("\n".join(lines), reply_markup=_admin_menu())


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, session: AsyncSession) -> None:
    users = await UserRepository(session).list_recent(20)
    total = await UserRepository(session).count()
    lines = ["👥 <b>Пользователи</b>", "", f"Всего: <b>{total}</b>", "Последние 20:"]
    rows = [[("🔍 Поиск", "admin:usersearch", "primary")]]
    for u in users:
        username = f"@{u.username}" if u.username else "без username"
        lines.append(f"• <code>{u.telegram_id}</code> · {escape(username)} · {float(u.balance or 0):.2f} {u.balance_currency}")
        rows.append([(f"{u.telegram_id} · {username[:16]}", f"admin:user:{u.id}")])
    rows.append([("⬅️ Назад", "admin:menu")])
    await replace_with_text_screen(callback, 
        "\n".join(lines),
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:usersearch")
async def admin_user_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_admin_user_search)
    await replace_with_text_screen(callback, 
        "🔍 <b>Поиск пользователя</b>\n\nВведите Telegram ID или username без @.",
        reply_markup=inline_keyboard([[("⬅️ Назад", "admin:users")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_admin_user_search)
async def admin_user_search(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().lstrip("@")
    await state.clear()
    repo = UserRepository(session)
    user = await repo.get_by_telegram_id(int(raw)) if raw.isdigit() else None
    if user is None and raw:
        users = await repo.list_recent(500)
        user = next((u for u in users if (u.username or "").lower() == raw.lower()), None)
    if user is None:
        await message.answer("Пользователь не найден.", reply_markup=_admin_menu())
        return
    await _send_user_card(message, session, user)


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_user_card(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.split(":", 2)[2])
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    await _edit_user_card(callback, session, user)
    await callback.answer()


@router.callback_query(F.data == "admin:grant")
async def admin_grant_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_grant_user_id)
    await replace_with_text_screen(callback, 
        "🎁 <b>Выдать подписку</b>\n\n"
        "Отправьте Telegram ID пользователя. Затем выберете тариф.\n"
        "Подписка будет создана в AdaptGroup, баланс интеграции спишется.",
        reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_grant_user_id)
async def admin_grant_user(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите Telegram ID числом.")
        return
    target = await UserRepository(session).get_by_telegram_id(int(raw))
    if target is None:
        await message.answer("Пользователь не найден в боте.")
        return
    await state.clear()
    plans = await PlanRepository(session).list_all()
    if not plans:
        await message.answer("Тарифов нет. Сначала синхронизируйте тарифы.", reply_markup=_admin_menu())
        return
    rows = [
        [(f"{p.name[:24]} · {format_price(float(p.retail_price), p.currency) if p.retail_price is not None else '—'}", f"admin:grantplan:{target.id}:{p.plan_uuid}", "primary")]
        for p in plans
        if p.is_active and not p.is_trial
    ]
    rows.append([("⬅️ Назад", "admin:menu")])
    await message.answer(
        f"🎁 Выберите тариф для пользователя <code>{target.telegram_id}</code>.",
        reply_markup=inline_keyboard(rows),
    )


@router.callback_query(F.data.startswith("admin:grantplan:"))
async def admin_grant_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, user_id_raw, plan_uuid = callback.data.split(":", 3)
    target = await UserRepository(session).get_by_id(int(user_id_raw))
    plan = await PlanRepository(session).get_by_uuid(plan_uuid)
    if target is None or plan is None:
        await callback.answer("Пользователь или тариф не найден.", show_alert=True)
        return
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_new_subscription_order(target.id, plan.plan_uuid)
    await order_service.orders.mark_paid(order)
    await session.commit()
    outcome = await order_service.provision(order)
    if outcome.provisioned or outcome.already_done:
        await replace_with_text_screen(callback, 
            "✅ Подписка выдана.\n\n"
            f"Пользователь: <code>{target.telegram_id}</code>\n"
            f"Тариф: <b>{escape(plan.name)}</b>",
            reply_markup=_admin_menu(),
        )
    else:
        await replace_with_text_screen(callback, 
            f"⚠️ Не удалось выдать подписку: {escape(outcome.error or 'ошибка')}",
            reply_markup=_admin_menu(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:userbalance:"))
async def admin_user_balance_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":", 2)[2])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminStates.waiting_user_balance_amount)
    await replace_with_text_screen(callback, 
        "💰 <b>Начислить баланс</b>\n\nВведите сумму в RUB, например <code>10</code>.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", f"admin:user:{user_id}")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_balance_amount)
async def admin_user_balance_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        await message.answer("Введите число, например 10.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return
    await state.update_data(balance_amount=str(amount))
    await state.set_state(AdminStates.waiting_user_balance_comment)
    await message.answer("✍️ Введите комментарий для пользователя. Например: <code>Приятного пользования!</code>")


@router.message(AdminStates.waiting_user_balance_comment)
async def admin_user_balance_comment(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    user_id = int(data["target_user_id"])
    amount = Decimal(str(data["balance_amount"]))
    comment = (message.text or "").strip() or "Приятного пользования!"
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        await state.clear()
        await message.answer("Пользователь не найден.", reply_markup=_admin_menu())
        return
    user.balance = Decimal(str(user.balance or 0)) + amount
    await session.commit()
    await state.clear()
    try:
        await message.bot.send_message(
            user.telegram_id,
            "🎁 <b>Вам начислен баланс от администрации</b>\n\n"
            f"Сумма: <b>{format_price(float(amount), user.balance_currency)}</b>\n"
            f"Комментарий: <i>{escape(comment)}</i>\n\n"
            f"Текущий баланс: <b>{format_price(float(user.balance or 0), user.balance_currency)}</b>",
        )
    except Exception:  # noqa: BLE001
        pass
    await message.answer(
        f"✅ Начислено {format_price(float(amount), user.balance_currency)} пользователю <code>{user.telegram_id}</code>.",
        reply_markup=_admin_menu(),
    )


@router.callback_query(F.data.startswith("admin:usergrant:"))
async def admin_user_grant(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = int(callback.data.split(":", 2)[2])
    target = await UserRepository(session).get_by_id(user_id)
    if target is None:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return
    plans = await PlanRepository(session).list_all()
    rows = [
        [(f"{p.name[:24]} · {format_price(float(p.retail_price), p.currency) if p.retail_price is not None else '—'}", f"admin:grantplan:{target.id}:{p.plan_uuid}", "primary")]
        for p in plans
        if p.is_active and not p.is_trial
    ]
    rows.append([("⬅️ К пользователю", f"admin:user:{target.id}")])
    await replace_with_text_screen(callback, 
        f"🎁 <b>Выдать подписку</b>\n\nПользователь: <code>{target.telegram_id}</code>",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:userextend:"))
async def admin_user_extend_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":", 2)[2])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminStates.waiting_user_extend_days)
    await replace_with_text_screen(callback, 
        "♻️ <b>Продлить текущую подписку</b>\n\n"
        "Введите число дней от <b>3</b>: <code>3</code>, <code>7</code>, <code>30</code>...",
        reply_markup=inline_keyboard([[("⬅️ Отмена", f"admin:user:{user_id}")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_user_extend_days)
async def admin_user_extend_days(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 3:
        await message.answer("AdaptGroup принимает кастомное продление минимум от 3 дней.")
        return
    days = int(raw)
    data = await state.get_data()
    user = await UserRepository(session).get_by_id(int(data["target_user_id"]))
    if user is None:
        await state.clear()
        await message.answer("Пользователь не найден.", reply_markup=_admin_menu())
        return
    sub = await SubscriptionRepository(session).get_active_for_user(user.id)
    if sub is None:
        await state.clear()
        await message.answer("У пользователя нет подписки.", reply_markup=_admin_menu())
        return
    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_action_order(
        user.id,
        OrderType.RENEW_CUSTOM,
        sub.subscription_uuid,
        amount=0,
        currency=settings.currency,
        extra={"days": days},
    )
    await order_service.orders.mark_paid(order)
    await session.commit()
    outcome = await order_service.provision(order)
    await state.clear()
    if outcome.provisioned or outcome.already_done:
        try:
            await message.bot.send_message(
                user.telegram_id,
                f"♻️ <b>Администрация продлила вашу подписку на {days} дн.</b>",
            )
        except Exception:  # noqa: BLE001
            pass
        await message.answer("✅ Подписка продлена.", reply_markup=_admin_menu())
    else:
        await message.answer(f"⚠️ Не удалось продлить: {escape(outcome.error or 'ошибка')}", reply_markup=_admin_menu())


async def _edit_user_card(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    text, rows = await _user_card(session, user)
    await replace_with_text_screen(callback, text, reply_markup=inline_keyboard(rows))


async def _send_user_card(message: Message, session: AsyncSession, user: User) -> None:
    text, rows = await _user_card(session, user)
    await message.answer(text, reply_markup=inline_keyboard(rows))


async def _user_card(session: AsyncSession, user: User):
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    orders = await OrderRepository(session).list_for_user(user.id, limit=3)
    username = f"@{user.username}" if user.username else "—"
    current = subs[0] if subs else None
    current_line = "—"
    if current is not None:
        current_line = f"{escape(current.plan_name or 'VPN')} до {format_date(current.expires_at)}"
    lines = [
        "👤 <b>Карточка пользователя</b>",
        "",
        f"ID: <code>{user.telegram_id}</code>",
        f"Username: <code>{escape(username)}</code>",
        f"Баланс: <b>{format_price(float(user.balance or 0), user.balance_currency)}</b>",
        f"Подписок: <b>{len(subs)}</b>",
        f"Текущая: <b>{current_line}</b>",
    ]
    if orders:
        lines.extend(["", "Последние операции:"])
        for order in orders:
            lines.append(f"• {order.order_type} · {format_price(float(order.amount), order.currency)} · {order.status}")
    rows = [
        [("💰 Начислить баланс", f"admin:userbalance:{user.id}", "success")],
        [("🎁 Выдать подписку", f"admin:usergrant:{user.id}", "primary"), ("♻️ Продлить", f"admin:userextend:{user.id}", "primary")],
        [("⬅️ Пользователи", "admin:users")],
    ]
    return "\n".join(lines), rows


def _purchase_label(plan) -> str:
    if plan.purchase_price is None:
        return "—"
    usd = Decimal(str(plan.purchase_price))
    rub = (usd * settings.adaptgroup_usd_to_rub_rate).quantize(Decimal("0.01"))
    return f"{usd} USD ({rub} RUB)"


# ── promo codes ───────────────────────────────────────────────
@router.callback_query(F.data == "admin:promos")
async def admin_promos(callback: CallbackQuery, session: AsyncSession) -> None:
    promos = await PromoRepository(session).list_recent(15)
    rows = [[("➕ Создать промокод", "admin:promo:create", "success")]]
    if not promos:
        text = (
            "🎟 <b>Промокоды на баланс</b>\n\n"
            "Промокодов пока нет. Создайте первый код: задайте название, сумму, "
            "лимит использований и/или дату окончания."
        )
    else:
        lines = ["🎟 <b>Промокоды на баланс</b>", "", "Последние 15 кодов:"]
        for promo in promos:
            status = _promo_status(promo)
            limit = "без лимита" if promo.max_uses is None else f"{promo.used_count}/{promo.max_uses}"
            expires = format_date(promo.expires_at) if promo.expires_at else "без даты"
            lines.append(
                f"{status} <code>{escape(promo.code)}</code> · "
                f"{format_price(float(promo.amount), promo.currency)} · "
                f"{limit} · до {expires}"
            )
        text = "\n".join(lines)
    rows.append([("⬅️ Назад", "admin:menu")])
    await replace_with_text_screen(callback, text, reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data == "admin:promo:create")
async def admin_promo_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_code)
    await replace_with_text_screen(callback, 
        "🎟 <b>Создать промокод</b>\n\n"
        "Введите код, который будет вводить пользователь.\n"
        "Например: <code>START100</code>",
        reply_markup=inline_keyboard([[("⬅️ Отмена", "admin:promos")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_promo_code)
async def admin_promo_code(message: Message, state: FSMContext, session: AsyncSession) -> None:
    code = (message.text or "").strip().upper()
    if not (3 <= len(code) <= 32) or not all(ch.isalnum() or ch in "-_" for ch in code):
        await message.answer("Код должен быть 3-32 символа: буквы, цифры, дефис или подчёркивание.")
        return
    if await PromoRepository(session).get_by_code(code):
        await message.answer("Такой промокод уже есть. Введите другой код.")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.waiting_promo_amount)
    await message.answer(
        "💰 <b>Сумма пополнения</b>\n\n"
        "Введите сумму в RUB, которая начислится пользователю. Например: <code>100</code>."
    )


@router.message(AdminStates.waiting_promo_amount)
async def admin_promo_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        await message.answer("Введите число, например <code>100</code> или <code>99.50</code>.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return
    await state.update_data(promo_amount=str(amount))
    await message.answer(
        "⚙️ <b>Ограничение промокода</b>\n\n"
        "Выберите, как ограничить промокод:",
        reply_markup=inline_keyboard(
            [
                [("🔢 Только количество", "admin:promo:mode:uses", "primary")],
                [("📅 Только дата", "admin:promo:mode:date", "primary")],
                [("🔢 + 📅 Количество и дата", "admin:promo:mode:both", "success")],
                [("⬅️ Отмена", "admin:promos")],
            ]
        ),
    )


@router.callback_query(F.data.startswith("admin:promo:mode:"))
async def admin_promo_mode(callback: CallbackQuery, state: FSMContext) -> None:
    mode = callback.data.rsplit(":", 1)[1]
    await state.update_data(promo_mode=mode)
    if mode in {"uses", "both"}:
        await state.set_state(AdminStates.waiting_promo_uses)
        await replace_with_text_screen(callback, 
            "🔢 <b>Количество использований</b>\n\n"
            "Введите общий лимит активаций. Например: <code>10</code>.",
            reply_markup=inline_keyboard([[("⬅️ Отмена", "admin:promos")]]),
        )
    else:
        await state.set_state(AdminStates.waiting_promo_expires)
        await replace_with_text_screen(callback, 
            "📅 <b>Дата окончания</b>\n\n"
            "Введите дату в формате <code>дд.мм.гггг</code> или <code>гггг-мм-дд</code>.",
            reply_markup=inline_keyboard([[("⬅️ Отмена", "admin:promos")]]),
        )
    await callback.answer()


@router.message(AdminStates.waiting_promo_uses)
async def admin_promo_uses(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Введите целое число больше нуля. Например: <code>10</code>.")
        return
    await state.update_data(promo_max_uses=int(raw))
    data = await state.get_data()
    if data.get("promo_mode") == "both":
        await state.set_state(AdminStates.waiting_promo_expires)
        await message.answer(
            "📅 <b>Дата окончания</b>\n\n"
            "Введите дату в формате <code>дд.мм.гггг</code> или <code>гггг-мм-дд</code>."
        )
        return
    await _finish_promo_create(message, state, session, user)


@router.message(AdminStates.waiting_promo_expires)
async def admin_promo_expires(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    expires_at = _parse_promo_date((message.text or "").strip())
    if expires_at is None:
        await message.answer("Не понял дату. Введите так: <code>30.06.2026</code> или <code>2026-06-30</code>.")
        return
    if expires_at <= datetime.now(timezone.utc):
        await message.answer("Дата окончания должна быть в будущем.")
        return
    await state.update_data(promo_expires_at=expires_at.isoformat())
    await _finish_promo_create(message, state, session, user)


async def _finish_promo_create(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    data = await state.get_data()
    code = str(data["promo_code"])
    amount = Decimal(str(data["promo_amount"]))
    max_uses = data.get("promo_max_uses")
    expires_raw = data.get("promo_expires_at")
    expires_at = datetime.fromisoformat(expires_raw) if expires_raw else None
    try:
        promo = await PromoRepository(session).create(
            code=code,
            amount=amount,
            max_uses=int(max_uses) if max_uses is not None else None,
            expires_at=expires_at,
            created_by_user_id=user.id,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        await message.answer(f"Не удалось создать промокод: {escape(str(exc)[:200])}", reply_markup=_admin_menu())
        await state.clear()
        return
    await state.clear()
    limit = "без лимита" if promo.max_uses is None else str(promo.max_uses)
    expires = format_date(promo.expires_at) if promo.expires_at else "без даты"
    await message.answer(
        "✅ <b>Промокод создан</b>\n\n"
        f"Код: <code>{escape(promo.code)}</code>\n"
        f"Сумма: <b>{format_price(float(promo.amount), promo.currency)}</b>\n"
        f"Использований: <b>{limit}</b>\n"
        f"Действует до: <b>{expires}</b>",
        reply_markup=inline_keyboard(
            [
                [("➕ Создать ещё", "admin:promo:create", "success")],
                [("🎟 К промокодам", "admin:promos")],
            ]
        ),
    )


def _parse_promo_date(raw: str) -> datetime | None:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            date = datetime.strptime(raw, fmt).date()
            return datetime.combine(date, time(23, 59, 59), tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _promo_status(promo) -> str:
    now = datetime.now(timezone.utc)
    if not promo.is_active:
        return "🚫"
    if promo.expires_at is not None:
        expires_at = promo.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            return "⌛"
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return "🔚"
    return "✅"


# ── plan sync ────────────────────────────────────────────────
@router.callback_query(F.data == "admin:syncplans")
async def admin_sync_plans(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer("Синхронизирую…")
    service = PlanService(session, get_client())
    try:
        plans = await service.sync_plans()
    except Exception as exc:  # noqa: BLE001
        await replace_with_text_screen(callback, 
            f"❌ Ошибка синхронизации: {escape(str(exc)[:200])}",
            reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]]),
        )
        return
    await replace_with_text_screen(callback, 
        f"✅ Синхронизировано тарифов: <b>{len(plans)}</b>",
        reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]]),
    )


@router.callback_query(F.data == "admin:integration")
async def admin_integration(callback: CallbackQuery, session: AsyncSession) -> None:
    plan_repo = PlanService(session, get_client()).repo
    last_sync = await plan_repo.latest_sync()
    # NEVER show secret values — only configured/not + masked hint.
    text = (
        "🔌 <b>Состояние интеграции</b>\n\n"
        f"Base URL: <code>{escape(settings.adaptgroup_base_url)}</code>\n"
        f"API key: {'настроен' if settings.adaptgroup_api_key else '❌ не задан'} "
        f"({mask_secret(settings.adaptgroup_api_key)})\n"
        f"API key id: {'настроен' if settings.adaptgroup_api_key_id else '❌ не задан'}\n"
        f"Webhook secret: {'настроен' if settings.adaptgroup_webhook_secret else '❌ не задан'}\n"
        f"Payment provider: <b>{escape(settings.payment_provider)}</b>\n"
        f"DEV_MODE: <b>{'ON' if settings.dev_mode else 'off'}</b>\n"
        f"Последняя синхронизация тарифов: {format_date(last_sync)}"
    )
    await replace_with_text_screen(callback, 
        text, reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]])
    )
    await callback.answer()


def _plan_style(plan) -> str:
    style = str(getattr(plan, "button_style", "primary") or "primary")
    return style if style in {item[0] for item in PLAN_BUTTON_STYLES} else "primary"


def _plan_button_style(plan) -> str:
    style = _plan_style(plan)
    return next((label for key, label in PLAN_BUTTON_STYLES if key == style), "🔵 Синяя")


def _plan_button_emoji_label(plan) -> str:
    key = getattr(plan, "button_emoji_key", None) or _auto_plan_emoji_key(plan)
    fallback = EMOJI_IDS.get(str(key), EMOJI_IDS["subs"])[0]
    preset = next((label for preset_key, label in PLAN_EMOJI_PRESETS if preset_key == key), None)
    return preset or fallback


def _auto_plan_emoji_key(plan) -> str:
    name = (getattr(plan, "name", "") or "").lower()
    if "ultra" in name or "ультра" in name:
        return "crown"
    if "pro" in name or "про" in name:
        return "diamond"
    if "standard" in name or "стандарт" in name:
        return "star"
    return "subs"


# ── broadcast ────────────────────────────────────────────────
@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_broadcast_text)
    await replace_with_text_screen(callback, 
        "📣 Отправьте текст рассылки (HTML поддерживается).",
        reply_markup=inline_keyboard([[("⬅️ Назад", "admin:menu")]]),
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast_text)
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    if not text.strip():
        await message.answer("Пустое сообщение не отправляется.")
        return
    await state.update_data(broadcast_text=text)
    await state.set_state(AdminStates.confirm_broadcast)
    await message.answer(
        f"📣 <b>Предпросмотр рассылки:</b>\n\n{text}\n\n— Отправить всем пользователям?",
        reply_markup=inline_keyboard(
            [[("✅ Отправить", "admin:broadcast:send", "danger")], [("⬅️ Отмена", "admin:menu")]]
        ),
    )


@router.callback_query(AdminStates.confirm_broadcast, F.data == "admin:broadcast:send")
async def broadcast_send(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()
    if not text:
        await callback.answer("Текст не найден.", show_alert=True)
        return

    ids = await UserRepository(session).all_telegram_ids(only_unblocked=True)
    await replace_with_text_screen(callback, f"📣 Отправляю {len(ids)} пользователям…")
    sent = failed = 0
    for tg_id in ids:
        try:
            await callback.bot.send_message(tg_id, text)
            sent += 1
        except Exception:  # noqa: BLE001
            failed += 1
    await callback.message.answer(
        f"📣 Готово. Отправлено: <b>{sent}</b>, не доставлено: <b>{failed}</b>",
        reply_markup=_admin_menu(),
    )
    await callback.answer()
