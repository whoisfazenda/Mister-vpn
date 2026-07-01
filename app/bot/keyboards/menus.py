"""Menu and screen keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from app.bot.keyboards.factory import (
    inline_keyboard,
    make_button,
    make_copy_button,
    make_url_button,
)
from app.core.config import settings
from app.db.models.subscription import VPNSubscription
from aiogram.types import InlineKeyboardButton

SUPPORT_URL = "https://t.me/mistervpnsup_bot"


def main_menu(*, is_admin: bool = False, show_trial: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [("🛒 Купить VPN", "buy:list", "success"), ("👤 Профиль", "profile:open", "primary")],
    ]
    if show_trial:
        rows.append([("💎 Пробный период 7 дней", "trial:claim", "primary")])
    rows.append([("💡 Помощь", "help:open")])
    if is_admin:
        rows.append([("🛠 Админ-панель", "admin:menu", "danger")])
    return inline_keyboard(rows)


def back_to_menu(label: str = "⬅️ В меню") -> InlineKeyboardMarkup:
    return inline_keyboard([[(label, "menu:open")]])


def support_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append([make_url_button("💬 Написать в поддержку", settings.support_url or SUPPORT_URL)])
    rows.append([make_button("⬅️ В меню", "menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_url_button("📢 Новостной канал", "https://t.me/mistervpn_news")],
            [make_url_button("💬 Поддержка", settings.support_url or SUPPORT_URL)],
            [make_button("📲 Инструкция по подключению", "help:connect", "primary")],
            [make_button("⬅️ В меню", "menu:open")],
        ]
    )


def connect_guide_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                make_url_button(
                    "💻 Windows / macOS",
                    "https://telegra.ph/Kak-podklyuchit-Mister-VPN-na-WindowsMacOS-07-01",
                )
            ],
            [
                make_url_button(
                    "📱 Android / iOS",
                    "https://telegra.ph/Kak-podklyuchit-Mister-VPN-na-AndroidIOS-07-01",
                )
            ],
            [make_button("⬅️ Назад", "help:open")],
        ]
    )


def my_vpn_keyboard(sub: VPNSubscription) -> InlineKeyboardMarkup:
    rows: list[list] = []
    rows.append([make_button("🔗 Получить ссылку", "myvpn:link", "primary")])
    if sub.is_trial:
        rows.append([make_button("🛒 Купить основной тариф", "buy:list", "success")])
    else:
        rows.append(
            [
                make_button("♻️ Продлить", "renew:menu", "success"),
                make_button("🚀 Улучшить тариф", "upgrade:menu", "primary"),
            ]
        )
    rows.append([make_button("📱 Мои устройства", "devices:list")])
    # Traffic top-up only for limited plans.
    if not sub.is_unlimited_traffic:
        rows.append([make_button("⚡ Докупить трафик", "traffic:menu", "primary")])
    if sub.is_frozen:
        rows.append([make_button("▶️ Разморозить", "freeze:unfreeze", "primary")])
    else:
        rows.append([make_button("⏸ Заморозить", "freeze:confirm", "danger")])
    rows.append([make_button("⬅️ Назад", "menu:open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_link_keyboard(url: str) -> InlineKeyboardMarkup:
    rows: list[list] = [
        [make_url_button("🌐 Открыть ссылку", url)],
        [make_copy_button("📋 Скопировать ссылку", url)],
        [make_button("📲 Инструкция по подключению", "help:connect")],
        [make_button("⬅️ Назад", "myvpn:open")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def no_subscription_keyboard() -> InlineKeyboardMarkup:
    return inline_keyboard(
        [
            [("🛒 Купить VPN", "buy:list", "success")],
            [("⬅️ В меню", "menu:open")],
        ]
    )
