"""RollyPay provider tests."""
from __future__ import annotations

import hmac
from hashlib import sha256

import httpx
import pytest

from app.core.enums import PaymentStatus
from app.services.payments.rollypay import RollyPayError, RollyPayProvider


async def test_rollypay_create_payment_uses_required_headers_and_payload() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["api_key"] = request.headers.get("X-API-Key")
        seen["nonce"] = request.headers.get("X-Nonce")
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "payment_id": "pay_1",
                "order_id": "order-1",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/token",
                "amount": "199.00",
                "payment_currency": "RUB",
            },
        )

    provider = RollyPayProvider(
        base_url="https://rolly.test",
        api_key="rpk",
        signing_secret="sec",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.create_payment(
        order_uuid="order-1",
        amount=199,
        currency="RUB",
        description="VPN order",
        idempotency_key="idem-1",
    )

    assert result.payment_id == "pay_1"
    assert result.confirmation_url == "https://pay.rollypay.io/pay/token"
    assert result.status == PaymentStatus.PENDING
    assert seen["path"] == "/api/v1/payments"
    assert seen["api_key"] == "rpk"
    assert seen["nonce"]
    assert '"order_id":"order-1"' in str(seen["body"]).replace(" ", "")
    assert '"amount":"199.00"' in str(seen["body"]).replace(" ", "")


async def test_rollypay_create_payment_can_force_crypto_method() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "payment_id": "pay_crypto",
                "status": "created",
                "pay_url": "https://pay.rollypay.io/pay/crypto-token",
            },
        )

    provider = RollyPayProvider(
        base_url="https://rolly.test",
        api_key="rpk",
        transport=httpx.MockTransport(handler),
    )
    await provider.create_payment(
        order_uuid="order-crypto",
        amount=10,
        currency="RUB",
        description="VPN order",
        idempotency_key="idem-crypto",
        payment_method="crypto",
    )

    assert '"payment_method":"crypto"' in str(seen["body"]).replace(" ", "")


async def test_rollypay_webhook_signature_and_status_mapping() -> None:
    raw = b'{"event_type":"payment.paid","payment_id":"pay_1","order_id":"order-1","status":"paid"}'
    timestamp = "1781100000"
    secret = "signing-secret"
    signature = hmac.new(
        secret.encode("utf-8"), timestamp.encode("utf-8") + b"." + raw, sha256
    ).hexdigest()

    provider = RollyPayProvider(api_key="rpk", signing_secret=secret)
    result = await provider.handle_webhook(
        raw,
        {"X-Timestamp": timestamp, "X-Signature": signature},
    )

    assert result.payment_id == "pay_1"
    assert result.order_uuid == "order-1"
    assert result.event_type == "payment.paid"
    assert result.status == PaymentStatus.SUCCEEDED


async def test_rollypay_webhook_rejects_bad_signature() -> None:
    provider = RollyPayProvider(api_key="rpk", signing_secret="secret")
    with pytest.raises(RollyPayError):
        await provider.handle_webhook(
            b'{"status":"paid"}',
            {"X-Timestamp": "1", "X-Signature": "bad"},
        )
