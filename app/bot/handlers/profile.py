"""User profile cabinet: balance, subscriptions, history, promo codes."""
from __future__ import annotations

from urllib.parse import quote

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client
from app.bot.handlers._errors import friendly_error
from app.bot.keyboards.factory import inline_keyboard, make_url_button
from app.bot.premium_emoji import pe
from app.bot.screens import (
    PROFILE_IMAGE,
    PROMOCODE_IMAGE,
    SUBSCRIPTIONS_IMAGE,
    TRANSACTIONS_IMAGE,
    replace_with_photo_screen,
    replace_with_text_screen,
)
from app.bot.states import PromoStates
from app.core.enums import OrderStatus, OrderType
from app.db.models.user import User
from app.repositories.orders import OrderRepository
from app.repositories.promos import PromoRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import escape, format_date, format_gb_used, format_price

router = Router(name="profile")

_sub_tokens: dict[int, dict[str, int]] = {}
_device_tokens: dict[int, dict[str, dict[str, str]]] = {}


@router.callback_query(F.data == "profile:open")
async def profile_open(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    active = sum(1 for sub in subs if sub.is_effectively_active)
    current = subs[0] if subs else None
    current_line = "—"
    if current is not None:
        current_line = f"{escape(current.plan_name or 'VPN')} до {format_date(current.expires_at)}"
    text = (
        f"{pe('profile')} <b>Профиль</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"{pe('balance')} Баланс: <b>{float(user.balance or 0):.2f} {user.balance_currency}</b>\n"
        f"{pe('subs')} Активных подписок: <b>{active}</b>\n"
        f"{pe('shield')} Текущая подписка: <b>{current_line}</b>"
    )
    await replace_with_photo_screen(
        callback,
        PROFILE_IMAGE,
        text,
        reply_markup=inline_keyboard(
            [
                [("💰 Пополнить баланс", "balance:topup", "success")],
                [("📋 Мои подписки", "profile:subs", "primary")],
                [("📜 История транзакций", "profile:history")],
                [("🎟 Активировать промокод", "profile:promo", "primary")],
                [("⬅️ Назад", "menu:open")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "profile:subs")
async def profile_subscriptions(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    if not subs:
        await replace_with_photo_screen(
            callback,
            SUBSCRIPTIONS_IMAGE,
            f"{pe('subs')} <b>Мои подписки</b>\n\nУ вас пока нет купленных подписок.",
            reply_markup=inline_keyboard([[("🛒 Купить VPN", "buy:list", "success")], [("⬅️ В профиль", "profile:open")]]),
        )
        await callback.answer()
        return
    tokens: dict[str, int] = {}
    rows = []
    lines = [f"{pe('subs')} <b>Мои подписки</b>", ""]
    for idx, sub in enumerate(subs, start=1):
        token = str(idx)
        tokens[token] = sub.id
        status = (
            "истекла"
            if sub.is_expired
            else "заморожена"
            if sub.is_frozen
            else "активна"
            if sub.is_active
            else "неактивна"
        )
        lines.append(f"{idx}. <b>{escape(sub.plan_name or 'VPN')}</b> · {status} · до {format_date(sub.expires_at)}")
        button_style = "success" if sub.is_effectively_active else "danger"
        button_icon = "✅" if sub.is_effectively_active else "⛔️"
        rows.append(
            [
                (
                    f"{button_icon} {sub.plan_name or 'VPN'} #{idx}",
                    f"profile:sub:{token}",
                    button_style,
                )
            ]
        )
    _sub_tokens[user.telegram_id] = tokens
    rows.append([("⬅️ В профиль", "profile:open")])
    await replace_with_photo_screen(
        callback,
        SUBSCRIPTIONS_IMAGE,
        "\n".join(lines),
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("profile:sub:"))
async def profile_subscription_card(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    token = callback.data.split(":", 2)[2]
    sub_id = _sub_tokens.get(user.telegram_id, {}).get(token)
    if not sub_id:
        await callback.answer("Откройте список подписок заново.", show_alert=True)
        return
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    sub = next((s for s in subs if s.id == sub_id), None)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    service = SubscriptionService(session, get_client())
    devices_count: int | None = None
    try:
        devices_count = len(await service.get_devices(sub))
    except Exception:  # noqa: BLE001
        devices_count = None
    status = (
        f"{pe('inactive')} истекла"
        if sub.is_expired
        else f"{pe('frozen')} заморожена"
        if sub.is_frozen
        else f"{pe('active')} активна"
        if sub.is_active
        else f"{pe('inactive')} неактивна"
    )
    traffic = "безлимит" if sub.is_unlimited_traffic else format_gb_used(sub.traffic_used_bytes, sub.traffic_limit_bytes)
    devices_line = _devices_usage_label(devices_count, sub.max_devices)
    text = (
        f"{pe('shield')} <b>Подписка</b>\n\n"
        f"{pe('subs')} Тариф: <b>{escape(sub.plan_name or 'VPN')}</b>\n"
        f"{pe('sparkles')} Статус: <b>{status}</b>\n"
        f"{pe('time')} Действует до: <b>{format_date(sub.expires_at)}</b>\n"
        f"{pe('devices')} Устройства: <b>{devices_line}</b>\n"
        f"{pe('traffic')} Трафик: <b>{traffic}</b>\n\n"
        f"{pe('link')} Ссылка:\n<code>{escape(sub.subscription_url or '—')}</code>"
    )
    rows = [[("📱 Устройства", f"profile:devices:{token}", "primary")]]
    if sub.is_trial:
        text += f"\n\n{pe('gift')} <b>Это пробная подписка. Ее нельзя продлить.</b>"
        rows.append([("🛒 Купить основной тариф", "buy:list", "success")])
    else:
        rows[0].append(("♻️ Продлить", f"renew:menu:{sub.subscription_uuid}", "success"))
    if sub.is_frozen:
        rows.append([("▶️ Разморозить", f"freeze:unfreeze:{sub.subscription_uuid}", "primary")])
    else:
        rows.append([("⏸ Заморозить", f"freeze:confirm:{sub.subscription_uuid}", "danger")])
    if not sub.is_unlimited_traffic:
        rows.append([("⚡ Докупить трафик", f"traffic:menu:{sub.subscription_uuid}", "primary")])
    rows.extend(
        [
            [("🖼 QR-код", f"profile:qr:{token}", "primary")],
            [("⬅️ К подпискам", "profile:subs")],
        ]
    )
    markup = inline_keyboard(rows)
    if sub.subscription_url:
        markup.inline_keyboard.insert(1, [make_url_button("🌐 Открыть подписку", sub.subscription_url)])
    await replace_with_text_screen(callback, text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("profile:qr:"))
async def profile_subscription_qr(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    token = callback.data.split(":", 2)[2]
    sub_id = _sub_tokens.get(user.telegram_id, {}).get(token)
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    sub = next((s for s in subs if s.id == sub_id), None)
    if sub is None or not sub.subscription_url:
        await callback.answer("У подписки нет ссылки.", show_alert=True)
        return
    qr_url = "https://api.qrserver.com/v1/create-qr-code/?size=320x320&data=" + quote(sub.subscription_url)
    await callback.message.answer_photo(
        qr_url,
        caption=f"{pe('web')} QR-код подписки. Отсканируйте его в VPN-клиенте.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("profile:devices:"))
async def profile_devices(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    token = callback.data.split(":", 2)[2]
    await _render_profile_devices(callback, session, user, token)
    await callback.answer()


@router.callback_query(F.data.startswith("profile:devdel:"))
async def profile_device_delete_confirm(callback: CallbackQuery, user: User) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Откройте устройства заново.", show_alert=True)
        return
    _, _, sub_token, dev_token = parts
    device_id = _device_tokens.get(user.telegram_id, {}).get(sub_token, {}).get(dev_token)
    if not device_id:
        await callback.answer("Список устройств устарел, откройте его заново.", show_alert=True)
        return
    await replace_with_text_screen(
        callback,
        f"{pe('delete')} <b>Удалить устройство?</b>\n\n"
        "После удаления слот освободится. Это устройство потеряет доступ к VPN, "
        "а новое устройство сможет подключиться по вашей ссылке.",
        reply_markup=inline_keyboard(
            [
                [("✅ Да, удалить", f"profile:devdelok:{sub_token}:{dev_token}", "danger")],
                [("⬅️ Назад к устройствам", f"profile:devices:{sub_token}")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("profile:devdelok:"))
async def profile_device_delete(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
) -> None:
    parts = callback.data.split(":")
    if len(parts) != 4:
        await callback.answer("Откройте устройства заново.", show_alert=True)
        return
    _, _, sub_token, dev_token = parts
    device_id = _device_tokens.get(user.telegram_id, {}).get(sub_token, {}).get(dev_token)
    if not device_id:
        await callback.answer("Список устройств устарел, откройте его заново.", show_alert=True)
        return
    sub = await _subscription_by_token(session, user, sub_token)
    if sub is None:
        await callback.answer("Откройте список подписок заново.", show_alert=True)
        return
    service = SubscriptionService(session, get_client())
    deleted_device: dict | None = None
    try:
        devices_before = await service.get_devices(sub)
        deleted_device = next(
            (d for d in devices_before if str(d.get("id") or "") == str(device_id)),
            None,
        )
        await service.delete_device(sub, device_id)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    _device_tokens.get(user.telegram_id, {}).get(sub_token, {}).pop(dev_token, None)
    await callback.answer("Устройство удалено.")
    await _render_profile_devices(
        callback,
        session,
        user,
        sub_token,
        deleted_device=deleted_device,
    )


async def _render_profile_devices(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    token: str,
    *,
    deleted_device: dict | None = None,
) -> None:
    sub = await _subscription_by_token(session, user, token)
    if sub is None:
        await callback.answer("Откройте список подписок заново.", show_alert=True)
        return
    service = SubscriptionService(session, get_client())
    try:
        devices = await service.get_devices(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return
    devices_usage = _devices_usage_label(len(devices), sub.max_devices)
    deleted_notice = _deleted_device_notice(deleted_device) if deleted_device else ""
    if not devices:
        text = deleted_notice + (
            f"{pe('devices')} <b>Устройства подписки</b>\n\n"
            f"Устройств: <b>{devices_usage}</b>\n\n"
            "Подключённых устройств пока нет."
        )
        rows = [[("⬅️ К подписке", f"profile:sub:{token}")]]
    else:
        lines = []
        if deleted_notice:
            lines.extend([deleted_notice.rstrip(), ""])
        lines.extend([f"{pe('devices')} <b>Устройства подписки</b>", "", f"Устройств: <b>{devices_usage}</b>", ""])
        rows = []
        tokens: dict[str, str] = {}
        for idx, dev in enumerate(devices, start=1):
            dev_token = str(idx)
            dev_id = str(dev.get("id") or "")
            lines.append(
                f"{idx}. <b>{escape(dev.get('name') or 'Устройство')}</b>\n"
                f"HWID: <code>{escape(dev.get('hwid') or '—')}</code>\n"
                f"IP: {escape(dev.get('ip_address') or '—')}\n"
                f"Активность: {escape(dev.get('last_seen') or '—')}"
            )
            if dev_id:
                tokens[dev_token] = dev_id
                rows.append(
                    [
                        (
                            f"🗑 Удалить {escape((dev.get('name') or 'устройство')[:24])}",
                            f"profile:devdel:{token}:{dev_token}",
                            "danger",
                        )
                    ]
                )
        text = "\n".join(lines)
        _device_tokens.setdefault(user.telegram_id, {})[token] = tokens
        rows.append([("⬅️ К подписке", f"profile:sub:{token}")])
    await replace_with_text_screen(callback, text, reply_markup=inline_keyboard(rows))


@router.callback_query(F.data == "profile:history")
async def profile_history(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    orders = await OrderRepository(session).list_for_user(user.id, limit=10)
    if not orders:
        text = f"{pe('history')} <b>История транзакций</b>\n\nОпераций пока нет."
    else:
        lines = [f"{pe('history')} <b>История транзакций</b>", ""]
        for order in orders:
            lines.append(_transaction_line(order))
        text = "\n".join(lines)
    await replace_with_photo_screen(
        callback,
        TRANSACTIONS_IMAGE,
        text,
        reply_markup=inline_keyboard([[("⬅️ В профиль", "profile:open")]]),
    )
    await callback.answer()


def _transaction_line(order) -> str:
    snapshot = order.snapshot or {}
    amount = format_price(float(order.amount), order.currency)
    status = _order_status_label(str(order.status))
    date = format_date(order.created_at)
    provider = _payment_provider_label(order.payment_provider, snapshot)
    order_type = str(order.order_type)

    if order_type == OrderType.BALANCE_TOPUP:
        return f"• {pe('balance')} Пополнение баланса · <b>{amount}</b> · {provider} · {status} · {date}"
    if order_type == OrderType.NEW_SUBSCRIPTION:
        plan_name = escape(snapshot.get("plan_name") or "VPN")
        return f"• {pe('subs')} Покупка тарифа <b>{plan_name}</b> · {amount} · {provider} · {status} · {date}"
    if order_type == OrderType.RENEW:
        return f"• {pe('renew')} Продление подписки · {amount} · {provider} · {status} · {date}"
    if order_type == OrderType.RENEW_CUSTOM:
        days = snapshot.get("days")
        details = f" на {days} дн." if days else ""
        return f"• {pe('calendar')} Продление{details} · {amount} · {provider} · {status} · {date}"
    if order_type == OrderType.TRAFFIC:
        gb = snapshot.get("amount_gb")
        details = f" {gb} ГБ" if gb else ""
        return f"• {pe('traffic')} Докупка трафика{details} · {amount} · {provider} · {status} · {date}"
    if order_type == OrderType.UPGRADE:
        return f"• {pe('rocket')} Улучшение тарифа · {amount} · {provider} · {status} · {date}"
    return f"• {pe('receipt')} Операция · {amount} · {provider} · {status} · {date}"


def _payment_provider_label(provider: str | None, snapshot: dict | None = None) -> str:
    snapshot = snapshot or {}
    if snapshot.get("payment_method"):
        return escape(str(snapshot["payment_method"]))
    labels = {
        "balance": "баланс",
        "yookassa": "карта / СБП",
        "rollypay": "крипто",
        "mock": "тест",
        "free_trial": "бесплатно",
    }
    return labels.get(str(provider or "").lower(), str(provider or "—"))


def _order_status_label(status: str) -> str:
    labels = {
        str(OrderStatus.PENDING): "ожидает оплаты",
        str(OrderStatus.PAID): "оплачено",
        str(OrderStatus.PROVISIONING): "выдаётся",
        str(OrderStatus.COMPLETED): "успешно",
        str(OrderStatus.FAILED): "ошибка",
        str(OrderStatus.CANCELLED): "отменено",
    }
    return labels.get(status, status)


@router.callback_query(F.data == "profile:promo")
async def profile_promo_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoStates.waiting_code)
    await replace_with_photo_screen(
        callback,
        PROMOCODE_IMAGE,
        f"{pe('promo')} <b>Промокод</b>\n\nВведите промокод сообщением.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", "profile:open")]]),
    )
    await callback.answer()


@router.message(PromoStates.waiting_code)
async def profile_promo_apply(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    code = (message.text or "").strip().upper()
    promo_repo = PromoRepository(session)
    promo = await promo_repo.get_by_code(code)
    if promo is None:
        await message.answer("Промокод не найден или уже не действует.")
        return
    ok, error = await promo_repo.redeem(promo, user)
    if not ok:
        await message.answer(error)
        return
    await session.commit()
    await state.clear()
    await message.answer(
        f"{pe('check')} Промокод активирован.\n\n"
        f"Баланс пополнен на <b>{float(promo.amount):.2f} {promo.currency}</b>.\n"
        f"Текущий баланс: <b>{float(user.balance or 0):.2f} {user.balance_currency}</b>.",
        reply_markup=inline_keyboard([[("👤 В профиль", "profile:open")]]),
    )


async def _subscription_by_token(session: AsyncSession, user: User, token: str):
    sub_id = _sub_tokens.get(user.telegram_id, {}).get(token)
    if not sub_id:
        return None
    subs = await SubscriptionRepository(session).list_for_user(user.id)
    return next((s for s in subs if s.id == sub_id), None)


def _devices_usage_label(used: int | None, total: int | None) -> str:
    used_text = str(used) if used is not None else "—"
    if total:
        return f"{used_text}/{total}"
    return used_text


def _deleted_device_notice(device: dict | None) -> str:
    name = escape((device or {}).get("name") or "Устройство")
    hwid = escape((device or {}).get("hwid") or "—")
    return (
        f"{pe('check')} <b>Устройство удалено</b>\n\n"
        f"Название: <b>{name}</b>\n"
        f"HWID: <code>{hwid}</code>\n\n"
        "Слот освобождён. В VPN-приложении на удалённом устройстве нажмите "
        "«Обновить подписку» или переподключитесь — доступ для этого устройства "
        "должен пропасть, а новое устройство сможет занять свободный слот.\n\n"
    )
