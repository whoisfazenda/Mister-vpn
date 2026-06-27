"""Promo code repository."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.db.models.promo import PromoCode, PromoRedemption
from app.db.models.user import User
from app.repositories.base import BaseRepository


class PromoRepository(BaseRepository):
    async def create(
        self,
        *,
        code: str,
        amount: Decimal,
        max_uses: int | None,
        expires_at: datetime | None,
        created_by_user_id: int | None,
    ) -> PromoCode:
        promo = PromoCode(
            code=code.upper(),
            amount=amount,
            currency=settings.currency,
            max_uses=max_uses,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )
        self.session.add(promo)
        await self.session.flush()
        return promo

    async def get_by_code(self, code: str) -> PromoCode | None:
        res = await self.session.execute(
            select(PromoCode).where(PromoCode.code == code.upper())
        )
        return res.scalar_one_or_none()

    async def list_recent(self, limit: int = 20) -> list[PromoCode]:
        res = await self.session.execute(
            select(PromoCode).order_by(PromoCode.created_at.desc()).limit(limit)
        )
        return list(res.scalars().all())

    async def count_active(self) -> int:
        now = datetime.now(timezone.utc)
        res = await self.session.execute(
            select(func.count())
            .select_from(PromoCode)
            .where(PromoCode.is_active.is_(True))
            .where((PromoCode.expires_at.is_(None)) | (PromoCode.expires_at > now))
        )
        return int(res.scalar_one())

    async def has_redeemed(self, promo_id: int, user_id: int) -> bool:
        res = await self.session.execute(
            select(PromoRedemption.id)
            .where(PromoRedemption.promo_code_id == promo_id)
            .where(PromoRedemption.user_id == user_id)
        )
        return res.scalar_one_or_none() is not None

    async def redeem(self, promo: PromoCode, user: User) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        if not promo.is_active:
            return False, "Промокод отключён."
        if promo.expires_at is not None and _aware_utc(promo.expires_at) < now:
            return False, "Срок действия промокода закончился."
        if promo.max_uses is not None and promo.used_count >= promo.max_uses:
            return False, "Лимит использований промокода закончился."
        if await self.has_redeemed(promo.id, user.id):
            return False, "Вы уже активировали этот промокод."

        amount = Decimal(str(promo.amount))
        redemption = PromoRedemption(
            promo_code_id=promo.id,
            user_id=user.id,
            amount=amount,
            currency=promo.currency,
        )
        self.session.add(redemption)
        promo.used_count += 1
        user.balance = Decimal(str(user.balance or 0)) + amount
        user.balance_currency = promo.currency
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return False, "Вы уже активировали этот промокод."
        return True, ""


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
