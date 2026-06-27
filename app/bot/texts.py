"""Centralized Russian UI texts and small builders.

All user-facing text lives here. Dynamic values are HTML-escaped at call sites
via app.utils.formatting.escape.
"""
from __future__ import annotations

from app.db.models.plan import VPNPlanSnapshot
from app.db.models.subscription import VPNSubscription
from app.bot.premium_emoji import pe
from app.utils.formatting import (
    escape,
    format_date,
    format_days,
    format_gb_used,
    format_price,
    format_traffic,
)

WELCOME = (
    "👋 <b>Добро пожаловать в VPN-сервис!</b>\n\n"
    "Быстрый и надёжный доступ к интернету без ограничений.\n"
    "Выберите действие в меню ниже."
)

MENU = "🏠 <b>Главное меню</b>\n\nЧем можем помочь?"

HELP = (
    "❓ <b>Помощь</b>\n\n"
    "• <b>Купить VPN</b> — выбрать тариф и оформить подписку.\n"
    "• <b>Мой VPN</b> — ссылка подключения, продление, устройства.\n"
    "• <b>Подключение</b> — как настроить VPN на ваших устройствах.\n"
    "• <b>Поддержка</b> — связаться с нами при любых вопросах.\n"
)

CONNECT_GUIDE = (
    f"{pe('phone')} <b>Как подключиться</b>\n\n"
    "1️⃣ Установите VPN-клиент:\n"
    "   • <b>iOS</b>: V2RayTun / Streisand\n"
    "   • <b>Android</b>: V2RayTun / Hiddify\n"
    "   • <b>Windows</b>: Hiddify / Nekoray\n"
    "   • <b>macOS</b>: V2RayTun / Hiddify\n\n"
    "2️⃣ Скопируйте вашу ссылку подписки в разделе «Мой VPN».\n"
    "3️⃣ В приложении выберите «Добавить из буфера обмена» или «Импорт по ссылке».\n"
    "4️⃣ Обновите подписку и подключитесь.\n\n"
    "Если что-то не получается — напишите в поддержку."
)

SUPPORT = (
    "💬 <b>Поддержка</b>\n\n"
    "Возникли вопросы или сложности? Мы на связи и поможем."
)

NO_SUBSCRIPTION = (
    "🛡 <b>Мой VPN</b>\n\n"
    "У вас пока нет активной подписки.\n"
    "Оформите тариф, чтобы начать пользоваться VPN."
)

BUY_INTRO = f"{pe('buy')} <b>Выберите тариф</b>\n\nДоступные планы подписки:"
BUY_EMPTY = (
    f"{pe('buy')} <b>Тарифы временно недоступны</b>\n\n"
    "Не удалось загрузить список тарифов. Попробуйте позже или напишите в поддержку."
)

ERROR_GENERIC = f"{pe('warning')} Что-то пошло не так. Попробуйте ещё раз чуть позже."
ERROR_RATE_LIMIT = "⏳ Сервис сейчас перегружен. Пожалуйста, повторите через минуту."
ERROR_NOT_FOUND = "🔍 Объект не найден. Обновите раздел и попробуйте снова."
ERROR_BAD_STATE = "🚫 Действие сейчас недоступно для вашей подписки."
ERROR_PAYMENT_PENDING = f"{pe('time')} Оплата пока не поступила. Попробуйте проверить чуть позже."


def plan_button_label(plan: VPNPlanSnapshot) -> str:
    price = format_price(
        float(plan.retail_price) if plan.retail_price is not None else None, plan.currency
    )
    parts = [escape(plan.name), price]
    if plan.duration_days:
        parts.append(format_days(plan.duration_days))
    return " · ".join(parts)


def plan_card(plan: VPNPlanSnapshot) -> str:
    price = format_price(
        float(plan.retail_price) if plan.retail_price is not None else None, plan.currency
    )
    lines = [
        f"{pe('subs')} <b>{escape(plan.name)}</b>",
        "",
        f"{pe('balance')} Цена: <b>{price}</b>",
    ]
    if plan.duration_days:
        lines.append(f"{pe('calendar')} Срок: {format_days(plan.duration_days)}")
    if plan.max_devices:
        lines.append(f"{pe('devices')} Устройств: до {plan.max_devices}")
    lines.append(f"{pe('traffic')} Трафик: {format_traffic(plan.traffic_limit_bytes)}")
    return "\n".join(lines)


def order_summary(plan: VPNPlanSnapshot) -> str:
    price = format_price(
        float(plan.retail_price) if plan.retail_price is not None else None, plan.currency
    )
    lines = [
        f"{pe('subs')} <b>Ваш заказ</b>",
        "",
        f"Тариф: <b>{escape(plan.name)}</b>",
    ]
    if plan.duration_days:
        lines.append(f"Срок: {format_days(plan.duration_days)}")
    if plan.max_devices:
        lines.append(f"Устройств: до {plan.max_devices}")
    lines.append(f"Трафик: {format_traffic(plan.traffic_limit_bytes)}")
    lines.append("")
    lines.append(f"К оплате: <b>{price}</b>")
    lines.append("")
    lines.append("Нажмите «Перейти к оплате», затем «Проверить оплату».")
    return "\n".join(lines)


def _status_label(sub: VPNSubscription) -> str:
    if sub.is_expired:
        return f"{pe('inactive')} истекла"
    if sub.is_frozen:
        return f"{pe('frozen')} заморожена"
    if sub.is_active:
        return f"{pe('active')} активна"
    return f"{pe('inactive')} неактивна"


def subscription_card(sub: VPNSubscription, devices_used: int | None = None) -> str:
    lines = [
        f"{pe('shield')} <b>Ваша VPN-подписка</b>",
        "",
        f"{pe('subs')} Тариф: <b>{escape(sub.plan_name or '—')}</b>",
        f"{pe('sparkles')} Статус: {_status_label(sub)}",
        f"{pe('time')} Действует до: {format_date(sub.expires_at)}",
    ]
    if sub.max_devices:
        used = devices_used if devices_used is not None else "?"
        lines.append(f"{pe('devices')} Устройства: {used}/{sub.max_devices}")
    if sub.is_unlimited_traffic:
        lines.append(f"{pe('traffic')} Трафик: безлимитный")
    else:
        lines.append(
            f"{pe('traffic')} Трафик: использовано "
            + format_gb_used(sub.traffic_used_bytes, sub.traffic_limit_bytes)
        )
    return "\n".join(lines)


def subscription_link(url: str) -> str:
    return (
        f"{pe('link')} <b>Ваша ссылка подписки</b>\n\n"
        f"<code>{escape(url)}</code>\n\n"
        "Скопируйте её и добавьте в VPN-клиент. "
        "Инструкция — по кнопке ниже."
    )
