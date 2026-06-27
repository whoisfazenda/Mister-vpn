"""One-time free trial flow."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.deps import get_client, get_payments
from app.bot.handlers._errors import friendly_error
from app.bot.keyboards.factory import inline_keyboard
from app.bot.keyboards.menus import my_vpn_keyboard
from app.bot.premium_emoji import pe
from app.bot.screens import replace_with_text_screen
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.plan import VPNPlanSnapshot
from app.db.models.user import User
from app.repositories.plans import PlanRepository
from app.services.orders import OrderService

logger = get_logger(__name__)
router = Router(name="trial")


@router.callback_query(F.data == "trial:claim")
async def claim_trial(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    if user.trial_claimed:
        await callback.answer("Пробный период уже был активирован.", show_alert=True)
        return

    plan = await _find_trial_plan(session)
    if plan is None:
        await replace_with_text_screen(
            callback,
            f"{pe('gift')} <b>Пробный период пока не настроен.</b>\n\n"
            "Администратору нужно выбрать 7-дневный тариф AdaptGroup в настройках "
            "<code>FREE_TRIAL_PLAN_UUID</code> или синхронизировать тарифы.",
            reply_markup=inline_keyboard(
                [
                    [("🛒 Купить VPN", "buy:list", "success")],
                    [("⬅️ В меню", "menu:open")],
                ]
            ),
        )
        await callback.answer()
        return

    order_service = OrderService(session, get_client(), get_payments())
    try:
        order = await order_service.create_free_trial_order(user.id, plan.plan_uuid)
        outcome = await order_service.provision(order)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Free trial activation failed for user %s: %s", user.telegram_id, exc)
        await callback.answer(friendly_error(exc), show_alert=True)
        return

    if not outcome.provisioned and not outcome.already_done:
        await replace_with_text_screen(
            callback,
            f"{pe('warning')} <b>Не удалось активировать пробный период.</b>\n\n"
            "Попробуйте ещё раз чуть позже. Если ошибка повторится, напишите в поддержку.",
            reply_markup=inline_keyboard([[("⬅️ В меню", "menu:open")]]),
        )
        await callback.answer()
        return

    user.trial_claimed = True
    await session.commit()
    sub = outcome.subscription
    if sub is None:
        await replace_with_text_screen(
            callback,
            f"{pe('check')} <b>Пробный период активирован.</b>\n\nОткройте профиль, чтобы посмотреть подписку.",
            reply_markup=inline_keyboard([[("👤 Профиль", "profile:open", "primary")]]),
        )
        await callback.answer("Пробный период активирован ✅")
        return

    await replace_with_text_screen(
        callback,
        f"{pe('gift')} <b>Пробный период активирован на 7 дней!</b>\n\n"
        + texts.subscription_card(sub)
        + "\n\nПробную подписку нельзя продлить. После теста выберите основной тариф.",
        reply_markup=my_vpn_keyboard(sub),
    )
    await callback.answer("Пробный период активирован ✅")


async def _find_trial_plan(session: AsyncSession) -> VPNPlanSnapshot | None:
    repo = PlanRepository(session)
    if settings.free_trial_plan_uuid:
        plan = await repo.get_by_uuid(settings.free_trial_plan_uuid)
        if plan and plan.is_active:
            return plan
    plans = await repo.list_active(include_trial=True, public_only=False)
    for plan in plans:
        name = plan.name.lower()
        if plan.duration_days == 7 and ("тест" in name or "test" in name or plan.is_trial):
            return plan
    for plan in plans:
        if plan.duration_days == 7:
            return plan
    return None
