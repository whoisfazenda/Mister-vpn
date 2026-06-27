"""Devices: list connected devices, confirm + delete to free a slot."""
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
from app.core.logging import get_logger
from app.db.models.user import User
from app.services.subscriptions import SubscriptionService
from app.utils.formatting import escape

logger = get_logger(__name__)
router = Router(name="devices")

# Short-lived in-memory map: token → device_id, to keep callback_data small &
# avoid trusting raw device ids from callbacks. Keyed per user.
_device_tokens: dict[int, dict[str, str]] = {}


@router.callback_query(F.data == "devices:list")
async def list_devices(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    try:
        devices = await service.get_devices(sub)
    except Exception as exc:  # noqa: BLE001
        await callback.answer(friendly_error(exc), show_alert=True)
        return

    if not devices:
        await replace_with_text_screen(
            callback,
            f"{pe('devices')} <b>Мои устройства</b>\n\nПодключённых устройств пока нет.",
            reply_markup=inline_keyboard([[("⬅️ К подпискам", "profile:subs")]]),
        )
        await callback.answer()
        return

    tokens: dict[str, str] = {}
    rows = []
    header = [f"{pe('devices')} <b>Мои устройства</b>", ""]
    for idx, dev in enumerate(devices, start=1):
        token = str(idx)
        tokens[token] = dev["id"]
        header.append(
            f"{idx}. <b>{escape(dev['name'])}</b>\n"
            f"HWID: <code>{escape(dev.get('hwid') or '—')}</code>\n"
            f"IP: {escape(dev.get('ip_address') or '—')}"
        )
        rows.append([(f"🗑 Удалить «{dev['name'][:20]}»", f"devices:del:{token}", "danger")])
    _device_tokens[user.telegram_id] = tokens
    rows.append([("⬅️ К подпискам", "profile:subs")])

    if sub.max_devices:
        header.append("")
        header.append(f"Использовано {len(devices)} из {sub.max_devices}.")

    await replace_with_text_screen(callback, "\n".join(header), reply_markup=inline_keyboard(rows))
    await callback.answer()


@router.callback_query(F.data.startswith("devices:del:"))
async def confirm_delete(callback: CallbackQuery, user: User) -> None:
    token = callback.data.split(":", 2)[2]
    tokens = _device_tokens.get(user.telegram_id, {})
    if token not in tokens:
        await callback.answer("Список устарел, откройте устройства заново.", show_alert=True)
        return
    rows = [
        [("✅ Да, удалить", f"devices:delok:{token}", "danger")],
        [("⬅️ Отмена", "devices:list")],
    ]
    await replace_with_text_screen(
        callback,
        f"{pe('delete')} <b>Удалить устройство?</b>\n\n"
        "Слот освободится, и вы сможете подключить другое устройство. "
        "Удалённое устройство потеряет доступ к VPN.",
        reply_markup=inline_keyboard(rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("devices:delok:"))
async def do_delete(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    token = callback.data.split(":", 2)[2]
    tokens = _device_tokens.get(user.telegram_id, {})
    device_id = tokens.get(token)
    if not device_id:
        await callback.answer("Список устарел, откройте устройства заново.", show_alert=True)
        return
    service = SubscriptionService(session, get_client())
    sub = await service.get_user_subscription(user.id)
    if sub is None:
        await callback.answer(texts.ERROR_NOT_FOUND, show_alert=True)
        return
    deleted_device = None
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
    tokens.pop(token, None)
    await callback.answer("Устройство удалено 🗑")
    await _render_deleted_device(callback, deleted_device)


async def _render_deleted_device(callback: CallbackQuery, device: dict | None) -> None:
    name = escape((device or {}).get("name") or "Устройство")
    hwid = escape((device or {}).get("hwid") or "—")
    await replace_with_text_screen(
        callback,
        f"{pe('check')} <b>Устройство удалено</b>\n\n"
        f"Название: <b>{name}</b>\n"
        f"HWID: <code>{hwid}</code>\n\n"
        "Слот освобождён. В VPN-приложении нажмите «Обновить подписку» "
        "или переподключитесь.",
        reply_markup=inline_keyboard(
            [
                [("📱 К устройствам", "devices:list", "primary")],
                [("⬅️ К подпискам", "profile:subs")],
            ]
        ),
    )
