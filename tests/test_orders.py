"""Order creation and idempotent provisioning tests."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.enums import OrderStatus, OrderType, PaymentStatus
from app.db.models.plan import VPNPlanSnapshot
from app.db.models.user import User
from app.repositories.orders import OrderRepository
from app.services.orders import OrderService
from app.services.payments.base import PaymentProvider, PaymentResult, WebhookResult
from app.services.payments.mock import MockPaymentProvider

GB = 1024 ** 3


class FakeAdaptGroupClient:
    """Records create calls and returns a deterministic subscription payload."""

    def __init__(self) -> None:
        self.create_calls = 0

    async def start(self) -> None:  # noqa: D401
        pass

    async def create_subscription(self, *, plan_uuid, external_user_id, idempotency_key):
        self.create_calls += 1
        return {
            "uuid": "sub-123",
            "subscription_url": "https://api.test/sub/sub-123",
            "plan_id": plan_uuid,
            "plan_name": "Базовый",
            "max_devices": 3,
            "traffic_limit_gb": 50,
            "expires_at": "2030-01-01T00:00:00Z",
            "external_user_id": external_user_id,
        }


class SucceededPollingPaymentProvider(PaymentProvider):
    name = "polling"

    async def create_payment(
        self,
        *,
        order_uuid: str,
        amount: float,
        currency: str,
        description: str,
        idempotency_key: str,
        payment_method: str | None = None,
    ) -> PaymentResult:
        return PaymentResult(
            payment_id=f"pay_{order_uuid}",
            confirmation_url="https://pay.test",
            status=PaymentStatus.PENDING,
        )

    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        return PaymentStatus.SUCCEEDED

    async def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        raise NotImplementedError


async def _setup(session) -> tuple[User, VPNPlanSnapshot]:
    user = User(telegram_id=555, username="u", first_name="U")
    session.add(user)
    plan = VPNPlanSnapshot(
        plan_uuid="p1",
        name="Базовый",
        retail_price=Decimal("199"),
        purchase_price=Decimal("100"),
        currency="RUB",
        duration_days=30,
        max_devices=3,
        traffic_limit_bytes=50 * GB,
        is_trial=False,
        is_active=True,
    )
    session.add(plan)
    await session.commit()
    return user, plan


async def test_create_order_freezes_snapshot(session) -> None:
    user, plan = await _setup(session)
    svc = OrderService(session, FakeAdaptGroupClient(), MockPaymentProvider())
    order = await svc.create_new_subscription_order(user.id, "p1")

    assert order.status == OrderStatus.PENDING
    assert order.order_type == OrderType.NEW_SUBSCRIPTION
    assert order.amount == Decimal("199")
    assert order.snapshot["plan_uuid"] == "p1"
    assert order.snapshot["retail_price"] == 199.0
    assert order.idempotency_key


async def test_cannot_buy_trial_plan(session) -> None:
    user = User(telegram_id=556)
    session.add(user)
    trial = VPNPlanSnapshot(
        plan_uuid="trial", name="Trial", retail_price=Decimal("0"),
        currency="RUB", duration_days=3, is_trial=True, is_active=True,
    )
    session.add(trial)
    await session.commit()

    svc = OrderService(session, FakeAdaptGroupClient(), MockPaymentProvider())
    with pytest.raises(ValueError):
        await svc.create_new_subscription_order(user.id, "trial")


async def test_check_payment_polling_marks_order_paid_without_webhook(session) -> None:
    user, plan = await _setup(session)
    provider = SucceededPollingPaymentProvider()
    svc = OrderService(session, FakeAdaptGroupClient(), provider)
    order = await svc.create_new_subscription_order(user.id, "p1")
    await svc.start_payment(order)

    paid = await svc.check_and_mark_paid(order)

    assert paid is True
    assert order.status == OrderStatus.PAID
    assert order.payment_id == f"pay_{order.order_uuid}"


async def test_provision_is_idempotent(session) -> None:
    user, plan = await _setup(session)
    fake = FakeAdaptGroupClient()
    svc = OrderService(session, fake, MockPaymentProvider())
    order = await svc.create_new_subscription_order(user.id, "p1")

    # Pay it.
    await svc.orders.mark_paid(order)
    await session.commit()

    # First provision succeeds and creates the subscription.
    outcome1 = await svc.provision(order)
    assert outcome1.provisioned is True
    assert outcome1.subscription is not None
    assert outcome1.subscription.subscription_uuid == "sub-123"
    assert order.status == OrderStatus.COMPLETED
    assert fake.create_calls == 1

    # Second provision must NOT create a second subscription.
    outcome2 = await svc.provision(order)
    assert outcome2.already_done is True
    assert outcome2.provisioned is False
    assert fake.create_calls == 1  # unchanged → no duplicate create


async def test_double_lock_prevents_duplicate(session) -> None:
    user, plan = await _setup(session)
    fake = FakeAdaptGroupClient()
    svc = OrderService(session, fake, MockPaymentProvider())
    order = await svc.create_new_subscription_order(user.id, "p1")
    await svc.orders.mark_paid(order)
    await session.commit()

    repo = OrderRepository(session)
    # First lock wins.
    assert await repo.try_lock_for_provisioning(order.id) is True
    # Status is now PROVISIONING → second lock fails.
    assert await repo.try_lock_for_provisioning(order.id) is False
