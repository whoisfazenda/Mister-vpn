"""FSM states."""
from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class CustomRenewStates(StatesGroup):
    waiting_days = State()


class BalanceStates(StatesGroup):
    waiting_topup_amount = State()


class PromoStates(StatesGroup):
    waiting_code = State()


class AdminStates(StatesGroup):
    waiting_user_id = State()
    waiting_plan_price = State()
    waiting_plan_name = State()
    waiting_period_label = State()
    waiting_grant_user_id = State()
    waiting_admin_user_search = State()
    waiting_user_balance_amount = State()
    waiting_user_balance_comment = State()
    waiting_user_extend_days = State()
    waiting_promo_code = State()
    waiting_promo_amount = State()
    waiting_promo_uses = State()
    waiting_promo_expires = State()
    waiting_broadcast_text = State()
    confirm_broadcast = State()
