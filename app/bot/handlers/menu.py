"""Start / main-menu handlers."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.keyboards.menus import main_menu
from app.bot.premium_emoji import pe
from app.bot.screens import (
    MAIN_IMAGE,
    answer_photo_screen,
    replace_with_photo_screen,
    replace_with_text_screen,
)
from app.core.config import settings
from app.db.models.user import User
from app.repositories.subscriptions import SubscriptionRepository

router = Router(name="menu")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.clear()
    await answer_photo_screen(
        message,
        MAIN_IMAGE,
        await _main_text(session, user),
        reply_markup=main_menu(
            is_admin=settings.is_admin(user.telegram_id),
            show_trial=not user.trial_claimed,
        ),
    )


@router.callback_query(F.data == "menu:open")
async def open_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession, user: User) -> None:
    await state.clear()
    await replace_with_photo_screen(
        callback,
        MAIN_IMAGE,
        await _main_text(session, user),
        reply_markup=main_menu(
            is_admin=settings.is_admin(user.telegram_id),
            show_trial=not user.trial_claimed,
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "help:open")
async def open_help(callback: CallbackQuery) -> None:
    from app.bot.keyboards.menus import back_to_menu

    await replace_with_text_screen(callback, texts.HELP, reply_markup=back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "help:connect")
async def open_connect(callback: CallbackQuery) -> None:
    from app.bot.keyboards.menus import back_to_menu

    await replace_with_text_screen(callback, texts.CONNECT_GUIDE, reply_markup=back_to_menu())
    await callback.answer()


@router.callback_query(F.data == "support:open")
async def open_support(callback: CallbackQuery) -> None:
    from app.bot.keyboards.menus import support_keyboard

    await replace_with_text_screen(callback, texts.SUPPORT, reply_markup=support_keyboard())
    await callback.answer()


@router.callback_query(F.data == "noop:copy")
async def noop_copy(callback: CallbackQuery) -> None:
    await callback.answer("Выделите ссылку выше и скопируйте вручную.", show_alert=False)


@router.callback_query(F.data.in_({"ref:open", "reviews:open", "news:open"}))
async def placeholder(callback: CallbackQuery) -> None:
    await callback.answer("Раздел скоро появится.", show_alert=True)


async def _main_text(session: AsyncSession, user: User) -> str:
    subscriptions = await SubscriptionRepository(session).list_for_user(user.id)
    active = sum(1 for sub in subscriptions if sub.is_effectively_active)
    return (
        f"{pe('shield')} <b>Добро пожаловать, {texts.escape(user.first_name or 'друг')}!</b>\n\n"
        f"◎ Telegram ID: <code>{user.telegram_id}</code>\n"
        f"{pe('balance')} Баланс: <b>{float(user.balance or 0):.2f} {user.balance_currency}</b>\n"
        f"{pe('subs')} Активных подписок: <b>{active}</b>\n\n"
        "⌄ Выберите действие ниже"
    )
