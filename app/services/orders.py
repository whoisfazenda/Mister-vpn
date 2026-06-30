"""Order service — payment + idempotent VPN provisioning.

State machine:
    pending  → user created order, awaiting payment
    paid     → payment confirmed, VPN not yet provisioned
    provisioning → exclusive lock while calling AdaptGroup (one-shot)
    completed → AdaptGroup action succeeded and persisted
    failed   → payment OK but provisioning failed (needs_manual_review when
               the outcome is UNKNOWN, e.g. network error on /subs/create)
    cancelled → user cancelled before payment

Key guarantees:
  * Provisioning is idempotent: a conditional UPDATE acquires the
    PROVISIONING lock, so a duplicate webhook or double-tap cannot create a
    second subscription.
  * /subs/create network errors are NEVER retried automatically — the order is
    flagged needs_manual_review for an admin to resolve safely.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.adaptgroup import (
    AdaptGroupError,
    AdaptGroupNetworkError,
    AdaptGroupVPNClient,
    _first,
)
from app.core.config import settings
from app.core.enums import OrderStatus, OrderType, PaymentStatus
from app.core.logging import get_logger
from app.db.models.order import Order
from app.db.models.subscription import VPNSubscription
from app.repositories.orders import OrderRepository
from app.repositories.plans import PlanRepository
from app.repositories.subscriptions import SubscriptionRepository
from app.services.payments.base import PaymentProvider
from app.services.subscriptions import SubscriptionService
from app.utils.idempotency import new_idempotency_key, new_uuid

logger = get_logger(__name__)


class ProvisionOutcome:
    """Result of attempting to provision an order."""

    def __init__(
        self,
        order: Order,
        *,
        provisioned: bool,
        already_done: bool = False,
        subscription: VPNSubscription | None = None,
        error: str | None = None,
    ) -> None:
        self.order = order
        self.provisioned = provisioned
        self.already_done = already_done
        self.subscription = subscription
        self.error = error


class OrderService:
    def __init__(
        self,
        session: AsyncSession,
        client: AdaptGroupVPNClient,
        payment_provider: PaymentProvider,
    ) -> None:
        self.session = session
        self.client = client
        self.payments = payment_provider
        self.orders = OrderRepository(session)
        self.plans = PlanRepository(session)
        self.subs = SubscriptionRepository(session)

    # ── order creation ───────────────────────────────────────
    async def create_new_subscription_order(
        self, user_id: int, plan_uuid: str
    ) -> Order:
        """Create a PENDING order for a brand-new subscription, freezing a
        snapshot of the plan so its price cannot change retroactively."""
        plan = await self.plans.get_by_uuid(plan_uuid)
        if plan is None:
            raise ValueError("План не найден")
        if plan.is_trial:
            raise ValueError("Пробные планы нельзя приобрести через бота")
        if not plan.is_active:
            raise ValueError("Этот тариф больше не доступен")

        amount = plan.retail_price if plan.retail_price is not None else Decimal("0")
        snapshot: dict[str, Any] = {
            "plan_uuid": plan.plan_uuid,
            "plan_name": plan.name,
            "retail_price": float(amount) if amount is not None else None,
            "currency": plan.currency,
            "duration_days": plan.duration_days,
            "max_devices": plan.max_devices,
            "traffic_limit_bytes": plan.traffic_limit_bytes,
        }
        order = Order(
            order_uuid=new_uuid(),
            user_id=user_id,
            order_type=OrderType.NEW_SUBSCRIPTION,
            snapshot=snapshot,
            amount=amount,
            currency=plan.currency,
            payment_provider=self.payments.name,
            status=OrderStatus.PENDING,
            idempotency_key=new_idempotency_key(),
        )
        self.orders.add(order)
        await self.session.commit()
        return order

    async def create_action_order(
        self,
        user_id: int,
        order_type: OrderType,
        subscription_uuid: str,
        *,
        amount: Decimal | float,
        currency: str,
        extra: dict[str, Any] | None = None,
    ) -> Order:
        """Create a PENDING order for renew/upgrade/traffic/custom actions."""
        snapshot: dict[str, Any] = {"subscription_uuid": subscription_uuid}
        if extra:
            snapshot.update(extra)
        order = Order(
            order_uuid=new_uuid(),
            user_id=user_id,
            order_type=order_type,
            snapshot=snapshot,
            amount=Decimal(str(amount)),
            currency=currency,
            payment_provider=self.payments.name,
            status=OrderStatus.PENDING,
            idempotency_key=new_idempotency_key(),
            subscription_uuid=subscription_uuid,
        )
        self.orders.add(order)
        await self.session.commit()
        return order

    async def create_balance_topup_order(self, user_id: int, amount: Decimal | float) -> Order:
        """Create a PENDING order that credits the user's internal bot balance."""
        order = Order(
            order_uuid=new_uuid(),
            user_id=user_id,
            order_type=OrderType.BALANCE_TOPUP,
            snapshot={"purpose": "balance_topup"},
            amount=Decimal(str(amount)),
            currency=settings.currency,
            payment_provider=self.payments.name,
            status=OrderStatus.PENDING,
            idempotency_key=new_idempotency_key(),
        )
        self.orders.add(order)
        await self.session.commit()
        return order

    async def create_free_trial_order(self, user_id: int, plan_uuid: str) -> Order:
        """Create a zero-price paid order for a one-time free trial subscription."""
        plan = await self.plans.get_by_uuid(plan_uuid)
        if plan is None:
            raise ValueError("Пробный тариф не найден")
        if not plan.is_active:
            raise ValueError("Пробный тариф больше не доступен")

        snapshot: dict[str, Any] = {
            "plan_uuid": plan.plan_uuid,
            "plan_name": plan.name,
            "retail_price": 0.0,
            "currency": plan.currency,
            "duration_days": plan.duration_days,
            "max_devices": plan.max_devices,
            "traffic_limit_bytes": plan.traffic_limit_bytes,
            "free_trial": True,
        }
        order = Order(
            order_uuid=new_uuid(),
            user_id=user_id,
            order_type=OrderType.NEW_SUBSCRIPTION,
            snapshot=snapshot,
            amount=Decimal("0"),
            currency=plan.currency,
            payment_provider="free_trial",
            status=OrderStatus.PAID,
            idempotency_key=new_idempotency_key(),
        )
        self.orders.add(order)
        await self.session.commit()
        return order

    async def pay_from_balance(self, order: Order) -> bool:
        """Deduct user balance and mark a VPN order paid, idempotently."""
        if order.status in (OrderStatus.PAID, OrderStatus.PROVISIONING, OrderStatus.COMPLETED):
            return True
        if order.status != OrderStatus.PENDING:
            return False
        user = order.user
        balance = Decimal(str(user.balance or 0))
        amount = Decimal(str(order.amount))
        if balance < amount:
            return False
        user.balance = balance - amount
        user.balance_currency = settings.currency
        await self.orders.mark_paid(order)
        await self.session.commit()
        return True

    # ── payment ──────────────────────────────────────────────
    async def start_payment(self, order: Order, payment_method: str | None = None) -> str:
        """Create a payment with the provider and return the confirmation URL."""
        provider = self._payment_provider_for_order(order)
        result = await provider.create_payment(
            order_uuid=order.order_uuid,
            amount=float(order.amount),
            currency=order.currency,
            description=f"VPN заказ {order.order_uuid[:8]}",
            idempotency_key=order.idempotency_key,
            payment_method=payment_method,
        )
        order.payment_provider = provider.name
        order.payment_id = result.payment_id
        await self.session.commit()
        return result.confirmation_url

    async def check_and_mark_paid(self, order: Order) -> bool:
        """Poll the payment provider; mark order paid on success. Idempotent."""
        if order.status in (OrderStatus.PAID, OrderStatus.PROVISIONING,
                            OrderStatus.COMPLETED):
            return True
        if order.status == OrderStatus.CANCELLED:
            return False
        if not order.payment_id:
            return False
        provider = self._payment_provider_for_order(order)
        try:
            status = await provider.get_payment_status(order.payment_id)
        except Exception as exc:
            if provider.name == "rollypay" and "payment not found" in str(exc).lower():
                from app.services.payments.factory import get_payment_provider

                fallback_provider = get_payment_provider("yookassa")
                status = await fallback_provider.get_payment_status(order.payment_id)
                order.payment_provider = fallback_provider.name
            else:
                raise
        if status == PaymentStatus.SUCCEEDED:
            await self.orders.mark_paid(order)
            await self.session.commit()
            return True
        return False

    def _payment_provider_for_order(self, order: Order) -> PaymentProvider:
        provider_name = str(order.payment_provider or "").strip()
        if not provider_name or provider_name == self.payments.name:
            return self.payments
        from app.services.payments.factory import get_payment_provider

        return get_payment_provider(provider_name)

    async def mark_paid_by_payment_id(self, payment_id: str) -> Order | None:
        """Used by a payment webhook. Idempotent: a second call is a no-op."""
        order = await self.orders.get_by_payment_id(payment_id)
        if order is None:
            return None
        if order.status == OrderStatus.PENDING:
            await self.orders.mark_paid(order)
            await self.session.commit()
        return order

    # ── provisioning (idempotent) ────────────────────────────
    async def provision(self, order: Order) -> ProvisionOutcome:
        """Provision a paid order against AdaptGroup exactly once.

        Acquires an atomic PROVISIONING lock. If already completed, returns
        ``already_done``. On UNKNOWN outcomes (network error during create)
        the order is flagged needs_manual_review and NOT retried automatically.
        """
        if order.status == OrderStatus.COMPLETED:
            sub = (
                await self.subs.get_by_uuid(order.subscription_uuid)
                if order.subscription_uuid
                else None
            )
            return ProvisionOutcome(order, provisioned=False, already_done=True, subscription=sub)

        # Acquire the lock: PAID/FAILED → PROVISIONING (atomic).
        locked = await self.orders.try_lock_for_provisioning(order.id)
        if not locked:
            await self.session.refresh(order)
            if order.status == OrderStatus.COMPLETED:
                sub = (
                    await self.subs.get_by_uuid(order.subscription_uuid)
                    if order.subscription_uuid
                    else None
                )
                return ProvisionOutcome(
                    order, provisioned=False, already_done=True, subscription=sub
                )
            return ProvisionOutcome(
                order, provisioned=False, error="Заказ уже обрабатывается"
            )

        try:
            outcome = await self._dispatch_provision(order)
        except AdaptGroupNetworkError as exc:
            # UNKNOWN outcome — do NOT retry blindly; flag for manual review.
            await self.orders.mark_failed(
                order,
                error_text=f"NETWORK/UNKNOWN: {exc}",
                needs_manual_review=True,
            )
            await self.session.commit()
            logger.error("Provisioning UNKNOWN outcome for order %s", order.order_uuid)
            return ProvisionOutcome(order, provisioned=False, error=str(exc))
        except AdaptGroupError as exc:
            # Definitive API error — safe to leave order retryable (FAILED).
            await self.orders.mark_failed(
                order,
                error_text=f"API {exc.status_code}: {exc}",
                needs_manual_review=False,
            )
            await self.session.commit()
            logger.warning("Provisioning failed for order %s: %s", order.order_uuid, exc)
            return ProvisionOutcome(order, provisioned=False, error=str(exc))

        await self.session.commit()
        return outcome

    async def _dispatch_provision(self, order: Order) -> ProvisionOutcome:
        await self.client.start()
        if order.order_type == OrderType.NEW_SUBSCRIPTION:
            return await self._provision_new(order)
        if order.order_type == OrderType.RENEW:
            data = await self.client.renew_subscription(order.subscription_uuid)
            return await self._apply_to_existing(order, data)
        if order.order_type == OrderType.RENEW_CUSTOM:
            days = int(order.snapshot.get("days", 0))
            data = await self.client.renew_subscription_custom(order.subscription_uuid, days)
            return await self._apply_to_existing(order, data)
        if order.order_type == OrderType.UPGRADE:
            plan_uuid = str(order.snapshot.get("plan_uuid"))
            data = await self.client.upgrade_subscription(order.subscription_uuid, plan_uuid)
            return await self._apply_to_existing(order, data)
        if order.order_type == OrderType.TRAFFIC:
            gb = int(order.snapshot.get("amount_gb", 0))
            data = await self.client.purchase_traffic(order.subscription_uuid, gb)
            return await self._apply_to_existing(order, data)
        if order.order_type == OrderType.BALANCE_TOPUP:
            return await self._apply_balance_topup(order)
        raise ValueError(f"Unknown order type {order.order_type}")

    async def _provision_new(self, order: Order) -> ProvisionOutcome:
        user = order.user
        external_user_id = str(user.telegram_id)
        plan_uuid = str(order.snapshot["plan_uuid"])
        data = await self.client.create_subscription(
            plan_uuid=plan_uuid,
            external_user_id=external_user_id,
            idempotency_key=order.idempotency_key,
        )
        sub_uuid = str(
            _first(
                data.get("subscription", data) if isinstance(data.get("subscription"), dict) else data,
                "uuid", "id", "subscription_id", "subscription_uuid", default="",
            )
        )
        if not sub_uuid:
            raise AdaptGroupError("AdaptGroup не вернул идентификатор подписки")

        sub = await self.subs.get_by_uuid(sub_uuid)
        if sub is None:
            sub = VPNSubscription(subscription_uuid=sub_uuid, user_id=order.user_id)
            self.subs.add(sub)
        sub_service = SubscriptionService(self.session, self.client)
        sub_service.apply_status_payload(sub, data)
        if order.snapshot.get("free_trial"):
            sub.is_trial = True
        # ensure plan name fallback from snapshot
        if not sub.plan_name:
            sub.plan_name = order.snapshot.get("plan_name")
        if not sub.plan_uuid:
            sub.plan_uuid = plan_uuid
        await self.session.flush()

        await self.orders.mark_completed(order, sub.subscription_uuid)
        return ProvisionOutcome(order, provisioned=True, subscription=sub)

    async def _apply_to_existing(self, order: Order, data: dict[str, Any]) -> ProvisionOutcome:
        sub = await self.subs.get_by_uuid(order.subscription_uuid)
        if sub is not None and data:
            sub_service = SubscriptionService(self.session, self.client)
            sub_service.apply_status_payload(sub, data)
            await self.session.flush()
        await self.orders.mark_completed(order, order.subscription_uuid)
        return ProvisionOutcome(order, provisioned=True, subscription=sub)

    async def _apply_balance_topup(self, order: Order) -> ProvisionOutcome:
        user = order.user
        user.balance = Decimal(str(user.balance or 0)) + Decimal(str(order.amount))
        user.balance_currency = settings.currency
        await self.orders.mark_completed(order, None)
        return ProvisionOutcome(order, provisioned=True, subscription=None)

    # ── dev / admin helpers ──────────────────────────────────
    async def dev_mark_paid(self, order: Order) -> bool:
        """Dev-only manual confirmation of a mock payment."""
        if not settings.dev_mode:
            raise PermissionError("DEV_MODE отключён")
        # Tell the mock provider too, so status polling stays consistent.
        marker = getattr(self.payments, "mark_paid", None)
        if callable(marker) and order.payment_id:
            marker(order.payment_id)
        if order.status == OrderStatus.PENDING:
            await self.orders.mark_paid(order)
            await self.session.commit()
        return order.status in (OrderStatus.PAID, OrderStatus.PROVISIONING, OrderStatus.COMPLETED)
