"""Webhook idempotency and network-error safety tests."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.clients.adaptgroup import AdaptGroupNetworkError
from app.core.enums import OrderStatus, WebhookProcessResult
from app.db.models.plan import VPNPlanSnapshot
from app.db.models.user import User
from app.services.orders import OrderService
from app.services.payments.mock import MockPaymentProvider
from app.services.webhooks import WebhookService, compute_event_key


class NoopClient:
    async def start(self) -> None:
        pass

    async def get_status(self, *_a, **_k):
        return {}


async def test_webhook_dedup(session) -> None:
    svc = WebhookService(session, NoopClient())
    payload = {"event": "subs.created", "timestamp": "2026-05-04T12:00:00Z",
               "data": {"subscription_id": "s1", "external_user_id": "123"}}
    raw = b'{"event":"subs.created"}'

    r1, _ = await svc.process("subs.created", payload, raw)
    assert r1 == WebhookProcessResult.PROCESSED

    # Same event again → duplicate, no reprocessing.
    r2, intent2 = await svc.process("subs.created", payload, raw)
    assert r2 == WebhookProcessResult.DUPLICATE
    assert intent2 is None


async def test_webhook_notify_intent(session) -> None:
    user = User(telegram_id=777)
    session.add(user)
    await session.commit()

    svc = WebhookService(session, NoopClient())
    payload = {
        "event": "subs.expires_in_24_hours",
        "timestamp": "2026-05-04T12:00:00Z",
        "data": {"external_user_id": "777", "subscription_id": "s2"},
    }
    result, intent = await svc.process("subs.expires_in_24_hours", payload, b"raw1")
    assert result == WebhookProcessResult.PROCESSED
    assert intent is not None
    assert intent.telegram_id == 777


async def test_device_added_webhook_notifies_once(session) -> None:
    svc = WebhookService(session, NoopClient())
    payload = {
        "event": "subs.device_added",
        "timestamp": "2026-05-04T12:00:00Z",
        "data": {
            "external_user_id": "777",
            "subscription_id": "s2",
            "device": {
                "id": 42,
                "name": "iPhone",
                "hwid": "xhwid",
                "device_os": "iOS",
                "device_model": "15 Pro",
                "ip_address": "127.0.0.1",
            },
        },
    }
    result, intent = await svc.process("subs.device_added", payload, b"raw-device-1")
    assert result == WebhookProcessResult.PROCESSED
    assert intent is not None
    assert intent.telegram_id == 777
    assert intent.details["name"] == "iPhone"
    assert intent.details["hwid"] == "xhwid"

    payload["timestamp"] = "2026-05-04T12:01:00Z"
    result2, intent2 = await svc.process("subs.device_added", payload, b"raw-device-2")
    assert result2 == WebhookProcessResult.PROCESSED
    assert intent2 is None

    payload["timestamp"] = "2026-05-04T12:02:00Z"
    payload["data"]["device"]["hwid"] = "xhwid-another-app"
    result3, intent3 = await svc.process("subs.device_added", payload, b"raw-device-3")
    assert result3 == WebhookProcessResult.PROCESSED
    assert intent3 is not None
    assert intent3.details["hwid"] == "xhwid-another-app"


def test_event_key_stable() -> None:
    p = {"event": "subs.created", "timestamp": "t", "data": {"id": "evt-1"}}
    k1 = compute_event_key("subs.created", b"a", p)
    k2 = compute_event_key("subs.created", b"b", p)
    # event id present → key independent of raw body
    assert k1 == k2 == "subs.created:evt-1"


# ── No blind retry on /subs/create network error ─────────────
class NetworkFailClient:
    def __init__(self) -> None:
        self.calls = 0

    async def start(self) -> None:
        pass

    async def create_subscription(self, **_k):
        self.calls += 1
        raise AdaptGroupNetworkError("boom")


async def test_create_network_error_flags_manual_review(session) -> None:
    user = User(telegram_id=888)
    session.add(user)
    plan = VPNPlanSnapshot(
        plan_uuid="p9", name="P", retail_price=Decimal("100"), currency="RUB",
        duration_days=30, max_devices=2, is_trial=False, is_active=True,
    )
    session.add(plan)
    await session.commit()

    client = NetworkFailClient()
    svc = OrderService(session, client, MockPaymentProvider())
    order = await svc.create_new_subscription_order(user.id, "p9")
    await svc.orders.mark_paid(order)
    await session.commit()

    outcome = await svc.provision(order)
    assert outcome.provisioned is False
    assert order.status == OrderStatus.FAILED
    assert order.needs_manual_review is True
    assert client.calls == 1  # exactly one attempt, no blind retry
