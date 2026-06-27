"""Order repository — includes atomic status transition for provisioning lock."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update

from app.core.enums import OrderStatus
from app.db.models.order import Order
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository):
    async def get_by_uuid(self, order_uuid: str) -> Order | None:
        res = await self.session.execute(
            select(Order).where(Order.order_uuid == order_uuid)
        )
        return res.scalar_one_or_none()

    async def get_by_id(self, order_id: int) -> Order | None:
        res = await self.session.execute(select(Order).where(Order.id == order_id))
        return res.scalar_one_or_none()

    async def get_by_payment_id(self, payment_id: str) -> Order | None:
        res = await self.session.execute(
            select(Order).where(Order.payment_id == payment_id)
        )
        return res.scalar_one_or_none()

    def add(self, order: Order) -> None:
        self.session.add(order)

    async def list_recent(self, limit: int = 10) -> list[Order]:
        res = await self.session.execute(
            select(Order).order_by(Order.created_at.desc()).limit(limit)
        )
        return list(res.scalars().all())

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[Order]:
        res = await self.session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(res.scalars().all())

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(Order))
        return int(res.scalar_one())

    async def count_by_status(self, status: OrderStatus) -> int:
        res = await self.session.execute(
            select(func.count()).select_from(Order).where(Order.status == status)
        )
        return int(res.scalar_one())

    async def try_lock_for_provisioning(self, order_id: int) -> bool:
        """Atomically move PAID/FAILED → PROVISIONING.

        Returns True iff this caller won the lock. Implemented as a conditional
        UPDATE so two concurrent provisioning attempts cannot both proceed.
        """
        res = await self.session.execute(
            update(Order)
            .where(
                Order.id == order_id,
                Order.status.in_([OrderStatus.PAID, OrderStatus.FAILED]),
            )
            .values(status=OrderStatus.PROVISIONING, error_text=None)
        )
        await self.session.flush()
        return res.rowcount == 1

    async def mark_paid(self, order: Order, payment_id: str | None = None) -> None:
        order.status = OrderStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        if payment_id:
            order.payment_id = payment_id

    async def mark_completed(self, order: Order, subscription_uuid: str | None) -> None:
        order.status = OrderStatus.COMPLETED
        order.completed_at = datetime.now(timezone.utc)
        order.needs_manual_review = False
        order.error_text = None
        if subscription_uuid:
            order.subscription_uuid = subscription_uuid

    async def mark_failed(
        self, order: Order, error_text: str, needs_manual_review: bool
    ) -> None:
        order.status = OrderStatus.FAILED
        order.error_text = error_text[:2000]
        order.needs_manual_review = needs_manual_review
