"""Plan service — sync plans from AdaptGroup into snapshots and read them."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.adaptgroup import AdaptGroupVPNClient, PlanDTO
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.plan import VPNPlanSnapshot
from app.repositories.plans import PlanRepository

logger = get_logger(__name__)


class PlanService:
    def __init__(self, session: AsyncSession, client: AdaptGroupVPNClient) -> None:
        self.session = session
        self.client = client
        self.repo = PlanRepository(session)

    async def sync_plans(self) -> list[VPNPlanSnapshot]:
        """Fetch plans from AdaptGroup and upsert snapshots.

        Trial plans are stored but flagged ``is_trial`` so the bot never offers
        them (they cannot be created via API).
        """
        await self.client.start()
        dtos: list[PlanDTO] = await self.client.list_plans()
        present: set[str] = set()
        snapshots: list[VPNPlanSnapshot] = []
        for dto in dtos:
            if not dto.plan_uuid:
                continue
            retail_price, currency = _retail_price_for_bot(dto)
            existing = await self.repo.get_by_uuid(dto.plan_uuid)
            if existing is not None and existing.manual_price:
                retail_price = existing.retail_price
                currency = existing.currency
            name = existing.name if existing is not None and existing.manual_name else dto.name
            present.add(dto.plan_uuid)
            snap = await self.repo.upsert(
                plan_uuid=dto.plan_uuid,
                name=name,
                purchase_price=dto.purchase_price,
                retail_price=retail_price,
                currency=currency,
                duration_days=dto.duration_days,
                max_devices=dto.max_devices,
                traffic_limit_bytes=dto.traffic_limit_bytes,
                is_trial=dto.is_trial,
                is_active=dto.is_active,
            )
            snapshots.append(snap)
        await self.repo.deactivate_missing(present)
        await self.session.commit()
        logger.info("Synced %d plans from AdaptGroup", len(snapshots))
        return snapshots

    async def get_purchasable_plans(self, *, auto_sync: bool = True) -> list[VPNPlanSnapshot]:
        """Active, non-trial plans. Re-syncs if cache is stale."""
        if auto_sync and await self._is_cache_stale():
            try:
                await self.sync_plans()
            except Exception as exc:  # noqa: BLE001 — fall back to cached data
                logger.warning("Plan sync failed, using cached snapshots: %s", exc)
        return await self.repo.list_active(include_trial=False, public_only=True)

    async def get_plan(self, plan_uuid: str) -> VPNPlanSnapshot | None:
        return await self.repo.get_by_uuid(plan_uuid)

    async def _is_cache_stale(self) -> bool:
        last = await self.repo.latest_sync()
        if last is None:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last
        return age > timedelta(seconds=settings.plans_cache_ttl)


def _retail_price_for_bot(dto: PlanDTO) -> tuple[Decimal | None, str]:
    """Return the user-facing price in the bot currency.

    AdaptGroup currently exposes plan prices in USD and may omit retail price.
    RollyPay regular payments are RUB, so the bot stores a RUB retail price.
    """
    source = dto.retail_price if dto.retail_price is not None else dto.purchase_price
    if source is None:
        return None, settings.currency

    amount = Decimal(str(source))
    if (dto.currency or "").upper() == "USD":
        amount *= settings.adaptgroup_usd_to_rub_rate
    markup = Decimal("1") + (settings.plan_markup_percent / Decimal("100"))
    amount = (amount * markup).quantize(Decimal("1"), rounding=ROUND_UP)
    return amount, settings.currency
