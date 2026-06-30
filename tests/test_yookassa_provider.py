"""YooKassa provider tests."""
from __future__ import annotations

import base64

import httpx

from app.core.enums import PaymentStatus
from app.services.payments.yookassa import YooKassaProvider


async def test_yookassa_create_payment_forces_sbp_and_redirect() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization")
        seen["idempotence"] = request.headers.get("Idempotence-Key")
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "id": "yk_pay_1",
                "status": "pending",
                "paid": False,
                "confirmation": {
                    "type": "redirect",
                    "confirmation_url": "https://yoomoney.ru/checkout/payments/sbp?id=1",
                },
            },
        )

    provider = YooKassaProvider(
        base_url="https://yookassa.test",
        shop_id="shop",
        secret_key="secret",
        return_url="https://example.test/return",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.create_payment(
        order_uuid="order-1",
        amount=199,
        currency="RUB",
        description="VPN order",
        idempotency_key="idem-1",
    )

    expected_auth = "Basic " + base64.b64encode(b"shop:secret").decode("ascii")
    body = str(seen["body"]).replace(" ", "")
    assert result.payment_id == "yk_pay_1"
    assert result.confirmation_url == "https://yoomoney.ru/checkout/payments/sbp?id=1"
    assert result.status == PaymentStatus.PENDING
    assert seen["path"] == "/v3/payments"
    assert seen["auth"] == expected_auth
    assert seen["idempotence"] == "idem-1"
    assert '"payment_method_data":{"type":"sbp"}' in body
    assert '"confirmation":{"type":"redirect","return_url":"https://example.test/return"}' in body
    assert '"capture":true' in body


async def test_yookassa_status_mapping() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "yk_pay_1", "status": "succeeded", "paid": True})

    provider = YooKassaProvider(
        base_url="https://yookassa.test",
        shop_id="shop",
        secret_key="secret",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.get_payment_status("yk_pay_1") == PaymentStatus.SUCCEEDED


async def test_yookassa_create_payment_can_force_bank_card() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "id": "yk_card_1",
                "status": "pending",
                "paid": False,
                "confirmation": {"confirmation_url": "https://yookassa.test/card"},
            },
        )

    provider = YooKassaProvider(
        base_url="https://yookassa.test",
        shop_id="shop",
        secret_key="secret",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.create_payment(
        order_uuid="order-card",
        amount=500,
        currency="RUB",
        description="VPN order",
        idempotency_key="idem-card",
        payment_method="bank_card",
    )

    body = str(seen["body"]).replace(" ", "")
    assert result.payment_id == "yk_card_1"
    assert '"payment_method_data":{"type":"bank_card"}' in body
