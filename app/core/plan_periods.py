"""Storefront period buckets for grouping AdaptGroup plans."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanPeriod:
    key: str
    label: str
    short_label: str
    emoji: str
    style: str


PLAN_PERIODS: tuple[PlanPeriod, ...] = (
    PlanPeriod("14d", "14 дней", "14 дн.", "📅", "primary"),
    PlanPeriod("1m", "1 месяц", "1 мес.", "1️⃣", "success"),
    PlanPeriod("3m", "3 месяца", "3 мес.", "3️⃣", "primary"),
    PlanPeriod("6m", "Полгода", "6 мес.", "6️⃣", "success"),
    PlanPeriod("12m", "12 месяцев", "12 мес.", "👑", "danger"),
)

_PERIOD_BY_KEY = {period.key: period for period in PLAN_PERIODS}


def period_label(key: str | None, *, short: bool = False) -> str:
    period = _PERIOD_BY_KEY.get(key or "")
    if period is None:
        return "не выбрано"
    return period.short_label if short else period.label


def valid_period_key(key: str | None) -> bool:
    return bool(key and key in _PERIOD_BY_KEY)
