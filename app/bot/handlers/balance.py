"""Internal bot balance: show, top up via payment provider, then spend on VPN."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.deps import get_client, get_payments
from app.bot.handlers.buy import render_payment_method_choice
from app.bot.keyboards.factory import inline_keyboard
from app.bot.premium_emoji import pe
from app.bot.screens import TOPUP_IMAGE, replace_with_photo_screen
from app.bot.states import BalanceStates
from app.core.config import settings
from app.db.models.user import User
from app.services.orders import OrderService

router = Router(name="balance")


@router.callback_query(F.data == "balance:open")
async def balance_open(callback: CallbackQuery, user: User) -> None:
    await replace_with_photo_screen(
        callback,
        TOPUP_IMAGE,
        _balance_text(user),
        reply_markup=inline_keyboard(
            [
                [("💳 Пополнить баланс", "balance:topup", "success")],
                [("🛒 Купить VPN", "buy:list", "primary")],
                [("⬅️ В меню", "menu:open")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:topup")
async def balance_topup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BalanceStates.waiting_topup_amount)
    sent = await replace_with_photo_screen(
        callback,
        TOPUP_IMAGE,
        f"{pe('balance')} <b>Пополнение баланса</b>\n\n"
        f"Введите сумму в рублях от {settings.min_balance_topup:.0f} "
        f"до {settings.max_balance_topup:.0f}.",
        reply_markup=inline_keyboard([[("⬅️ Отмена", "profile:open")]]),
    )
    if sent is not None:
        await state.update_data(topup_prompt_message_id=sent.message_id)
    await callback.answer()


@router.message(BalanceStates.waiting_topup_amount)
async def balance_topup_amount(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    user: User,
) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        await message.answer("Введите сумму числом, например 500.")
        return
    if amount < settings.min_balance_topup or amount > settings.max_balance_topup:
        await message.answer(
            f"Сумма должна быть от {settings.min_balance_topup:.0f} "
            f"до {settings.max_balance_topup:.0f} RUB."
        )
        return
    data = await state.get_data()
    await state.clear()
    prompt_message_id = data.get("topup_prompt_message_id")
    if prompt_message_id:
        try:
            await message.bot.delete_message(message.chat.id, int(prompt_message_id))
        except Exception:  # noqa: BLE001
            pass

    order_service = OrderService(session, get_client(), get_payments())
    order = await order_service.create_balance_topup_order(user.id, amount)

    await render_payment_method_choice(
        message,
        order.order_uuid,
        f"{pe('balance')} <b>Пополнение баланса</b>\n\n"
        f"Сумма: <b>{float(amount):.2f} RUB</b>",
        back_callback="profile:open",
        include_yookassa_sbp=True,
    )


def _balance_text(user: User) -> str:
    return (
        f"{pe('balance')} <b>Ваш баланс</b>\n\n"
        f"Доступно: <b>{float(user.balance or 0):.2f} {user.balance_currency}</b>\n\n"
        "Баланс можно пополнить через RollyPay, а потом оплачивать VPN внутри бота."
    )
