"""AdaptGroup client tests: error mapping and tolerant plan parsing.

Uses httpx MockTransport to mock the external API without network.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.clients.adaptgroup import (
    AdaptGroupInsufficientFunds,
    AdaptGroupNotFound,
    AdaptGroupRateLimited,
    AdaptGroupValidationError,
    AdaptGroupVPNClient,
)

GB = 1024 ** 3


def _make_client(handler) -> AdaptGroupVPNClient:
    client = AdaptGroupVPNClient(
        base_url="https://api.test", api_key="k", api_key_id="i", timeout=5
    )
    client._client = httpx.AsyncClient(
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
        headers={"X-Api-Key": "k"},
    )
    return client


def _request_json(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


async def test_list_plans_tolerant_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "plans": [
                    {
                        "id": "p1",
                        "name": "Базовый",
                        "price": 199,
                        "cost": 100,
                        "days": 30,
                        "devices": 3,
                        "traffic_limit_gb": 50,
                    },
                    {
                        "uuid": "p2",
                        "title": "Безлимит",
                        "retail_price": 499,
                        "duration_days": 90,
                        "max_devices": 5,
                    },
                ]
            },
        )

    client = _make_client(handler)
    plans = await client.list_plans()
    await client.close()

    assert len(plans) == 2
    p1, p2 = plans
    assert p1.plan_uuid == "p1"
    assert p1.name == "Базовый"
    assert p1.retail_price == 199
    assert p1.purchase_price == 100
    assert p1.duration_days == 30
    assert p1.max_devices == 3
    assert p1.traffic_limit_bytes == 50 * GB
    assert p1.is_unlimited_traffic is False

    assert p2.plan_uuid == "p2"
    assert p2.name == "Безлимит"
    assert p2.retail_price == 499
    assert p2.is_unlimited_traffic is True


async def test_list_plans_openapi_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/plans/list"
        assert _request_json(request) == {"api_key_id": "i"}
        return httpx.Response(
            200,
            json={
                "success": True,
                "plans": [
                    {
                        "uuid": "plan-openapi",
                        "name": "OpenAPI",
                        "devices": 5,
                        "days": 30,
                        "price_usd": "2.50",
                        "retail_price_usd": "5.00",
                        "traffic_limit_bytes": 107374182400,
                        "is_trial": False,
                        "is_active": True,
                    }
                ],
            },
        )

    client = _make_client(handler)
    plans = await client.list_plans()
    await client.close()

    assert len(plans) == 1
    plan = plans[0]
    assert plan.plan_uuid == "plan-openapi"
    assert plan.name == "OpenAPI"
    assert plan.purchase_price == 2.5
    assert plan.retail_price == 5.0
    assert plan.currency == "USD"
    assert plan.duration_days == 30
    assert plan.max_devices == 5
    assert plan.traffic_limit_bytes == 100 * GB


async def test_error_402_insufficient_funds() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"message": "Недостаточно средств"})

    client = _make_client(handler)
    with pytest.raises(AdaptGroupInsufficientFunds):
        await client.create_subscription("p1", "12345", "idem-1")
    await client.close()


async def test_error_404_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    client = _make_client(handler)
    with pytest.raises(AdaptGroupNotFound):
        await client.get_status("missing")
    await client.close()


async def test_error_429_rate_limited_on_create() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "rate"})

    client = _make_client(handler)
    with pytest.raises(AdaptGroupRateLimited):
        await client.create_subscription("p1", "12345", "idem-2")
    await client.close()


async def test_create_subscription_uses_openapi_field_names() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = _request_json(request)
        seen["idempotency_key"] = request.headers.get("Idempotency-Key")
        return httpx.Response(
            200,
            json={
                "subscription_uuid": "sub-1",
                "subscription_url": "https://api.test/sub/sub-1",
            },
        )

    client = _make_client(handler)
    await client.create_subscription("plan-1", "12345", "idem-1")
    await client.close()

    assert seen["path"] == "/subs/create"
    assert seen["body"] == {
        "api_key_id": "i",
        "plan_uuid": "plan-1",
        "external_user_id": "12345",
    }
    assert seen["idempotency_key"] == "idem-1"


async def test_subscription_actions_use_openapi_field_names() -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, _request_json(request)))
        return httpx.Response(200, json={"success": True})

    client = _make_client(handler)
    await client.renew_subscription_custom("sub-1", 14)
    await client.upgrade_subscription("sub-1", "plan-2")
    await client.purchase_traffic("sub-1", 10)
    await client.get_requests("sub-1", page=3, per_page=20)
    await client.delete_device("sub-1", "42")
    await client.close()

    assert seen == [
        ("/subs/renew/custom", {"api_key_id": "i", "subscription_uuid": "sub-1", "custom_days": 14}),
        ("/subs/upgrade", {"api_key_id": "i", "subscription_uuid": "sub-1", "new_plan_uuid": "plan-2"}),
        ("/subs/traffic", {"api_key_id": "i", "subscription_uuid": "sub-1", "gb_amount": 10}),
        ("/subs/requests", {"api_key_id": "i", "subscription_uuid": "sub-1", "offset": 40, "limit": 20}),
        ("/subs/devices/delete", {"api_key_id": "i", "subscription_uuid": "sub-1", "device_id": 42}),
    ]


async def test_custom_renew_rejects_less_than_three_days_before_api_call() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"success": True})

    client = _make_client(handler)
    with pytest.raises(AdaptGroupValidationError):
        await client.renew_subscription_custom("sub-1", 1)
    await client.close()
    assert called is False
