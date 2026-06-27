"""Runtime settings for storefront period buttons."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_periods import PLAN_PERIODS, PlanPeriod
from app.repositories.settings import SettingsRepository


@dataclass(frozen=True)
class PeriodView:
    key: str
    label: str
    default_label: str
    emoji: str
    style: str
    enabled: bool


class PlanPeriodService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = SettingsRepository(session)

    async def list_periods(self) -> list[PeriodView]:
        result: list[PeriodView] = []
        for period in PLAN_PERIODS:
            result.append(await self.get_period(period.key))
        return result

    async def get_period(self, key: str) -> PeriodView:
        period = _period_by_key(key)
        label = await self.repo.get(_label_key(key)) or period.label
        enabled_raw = await self.repo.get(_enabled_key(key))
        enabled = enabled_raw != "0"
        return PeriodView(
            key=period.key,
            label=label.strip() or period.label,
            default_label=period.label,
            emoji=period.emoji,
            style=period.style,
            enabled=enabled,
        )

    async def set_enabled(self, key: str, enabled: bool) -> None:
        _period_by_key(key)
        await self.repo.set(
            _enabled_key(key),
            "1" if enabled else "0",
            "Storefront period visibility",
        )

    async def set_label(self, key: str, label: str) -> None:
        period = _period_by_key(key)
        value = label.strip() or period.label
        await self.repo.set(_label_key(key), value, "Storefront period label")


def _period_by_key(key: str) -> PlanPeriod:
    for period in PLAN_PERIODS:
        if period.key == key:
            return period
    raise ValueError("Unknown period")


def _enabled_key(key: str) -> str:
    return f"storefront.period.{key}.enabled"


def _label_key(key: str) -> str:
    return f"storefront.period.{key}.label"
