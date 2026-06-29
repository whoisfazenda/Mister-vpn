"""Plan snapshot repository."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.plan import VPNPlanSnapshot
from app.repositories.base import BaseRepository


class PlanRepository(BaseRepository):
    async def get_by_uuid(self, plan_uuid: str) -> VPNPlanSnapshot | None:
        res = await self.session.execute(
            select(VPNPlanSnapshot).where(VPNPlanSnapshot.plan_uuid == plan_uuid)
        )
        return res.scalar_one_or_none()

    async def list_active(
        self, include_trial: bool = False, public_only: bool = False
    ) -> list[VPNPlanSnapshot]:
        stmt = select(VPNPlanSnapshot).where(VPNPlanSnapshot.is_active.is_(True))
        if not include_trial:
            stmt = stmt.where(VPNPlanSnapshot.is_trial.is_(False))
        if public_only:
            stmt = stmt.where(VPNPlanSnapshot.is_public.is_(True))
        stmt = stmt.order_by(
            VPNPlanSnapshot.retail_price.is_(None),
            VPNPlanSnapshot.retail_price.asc(),
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_active_by_period(
        self,
        period_group: str,
        *,
        include_trial: bool = False,
        public_only: bool = False,
    ) -> list[VPNPlanSnapshot]:
        stmt = (
            select(VPNPlanSnapshot)
            .where(VPNPlanSnapshot.is_active.is_(True))
            .where(VPNPlanSnapshot.period_group == period_group)
        )
        if not include_trial:
            stmt = stmt.where(VPNPlanSnapshot.is_trial.is_(False))
        if public_only:
            stmt = stmt.where(VPNPlanSnapshot.is_public.is_(True))
        stmt = stmt.order_by(
            VPNPlanSnapshot.max_devices.is_(None),
            VPNPlanSnapshot.max_devices.asc(),
            VPNPlanSnapshot.retail_price.is_(None),
            VPNPlanSnapshot.retail_price.asc(),
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_all(self) -> list[VPNPlanSnapshot]:
        res = await self.session.execute(
            select(VPNPlanSnapshot).order_by(VPNPlanSnapshot.synced_at.desc())
        )
        return list(res.scalars().all())

    async def upsert(self, **values: object) -> VPNPlanSnapshot:
        plan_uuid = str(values["plan_uuid"])
        existing = await self.get_by_uuid(plan_uuid)
        values["synced_at"] = datetime.now(timezone.utc)
        if existing is None:
            obj = VPNPlanSnapshot(**values)  # type: ignore[arg-type]
            self.session.add(obj)
            await self.session.flush()
            return obj
        for k, v in values.items():
            setattr(existing, k, v)
        await self.session.flush()
        return existing

    async def latest_sync(self) -> datetime | None:
        res = await self.session.execute(
            select(VPNPlanSnapshot.synced_at)
            .order_by(VPNPlanSnapshot.synced_at.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def deactivate_missing(self, present_uuids: set[str]) -> None:
        res = await self.session.execute(select(VPNPlanSnapshot))
        for plan in res.scalars().all():
            if plan.plan_uuid not in present_uuids and plan.is_active:
                plan.is_active = False
