"""YooKassa payment provider for SBP balance top-ups.

Docs: https://yookassa.ru/developers/payment-acceptance/integration-scenarios/manual-integration/other/sbp
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.enums import PaymentStatus
from app.services.payments.base import PaymentProvider, PaymentResult, WebhookResult


class YooKassaError(Exception):
    """Raised when YooKassa returns an error or a malformed response."""


class YooKassaProvider(PaymentProvider):
    name = "yookassa"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        shop_id: str | None = None,
        secret_key: str | None = None,
        return_url: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.yookassa_base_url).rstrip("/")
        self.shop_id = shop_id if shop_id is not None else settings.yookassa_shop_id
        self.secret_key = secret_key if secret_key is not None else settings.yookassa_secret_key
        self.return_url = (
            return_url
            if return_url is not None
            else settings.yookassa_return_url or settings.public_base_url or "https://t.me"
        )
        self.timeout = timeout or settings.yookassa_timeout
        self.transport = transport

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
        if not self.shop_id or not self.secret_key:
            raise YooKassaError("YOOKASSA_SHOP_ID/YOOKASSA_SECRET_KEY are not configured")

        payload: dict[str, Any] = {
            "amount": {
                "value": _money(amount),
                "currency": currency,
            },
            "confirmation": {
                "type": "redirect",
                "return_url": self.return_url,
            },
            "capture": True,
            "description": description,
            "metadata": {
                "order_uuid": order_uuid,
                "idempotency_key": idempotency_key,
                "source": "mister_vpn_bot",
            },
        }
        if payment_method in {"card", "bank_card", "sbp"}:
            payment_method_type = "bank_card" if payment_method in {"card", "bank_card"} else "sbp"
            payload["payment_method_data"] = {"type": payment_method_type}

        data = await self._request(
            "POST",
            "/v3/payments",
            headers={"Idempotence-Key": idempotency_key},
            json=payload,
        )
        payment_id = str(data.get("id") or "")
        confirmation = data.get("confirmation") if isinstance(data.get("confirmation"), dict) else {}
        confirmation_url = str(confirmation.get("confirmation_url") or "")
        if not payment_id or not confirmation_url:
            raise YooKassaError("YooKassa did not return id/confirmation_url")
        return PaymentResult(
            payment_id=payment_id,
            confirmation_url=confirmation_url,
            status=_map_status(data),
            raw=data,
        )

    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        if not payment_id:
            return PaymentStatus.PENDING
        data = await self._request("GET", f"/v3/payments/{payment_id}")
        return _map_status(data)

    async def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise YooKassaError("Invalid YooKassa webhook JSON") from exc
        obj = payload.get("object") if isinstance(payload.get("object"), dict) else payload
        return WebhookResult(
            payment_id=str(obj.get("id") or ""),
            order_uuid=(obj.get("metadata") or {}).get("order_uuid"),
            event_type=str(payload.get("event") or payload.get("type") or ""),
            status=_map_status(obj),
            raw=payload,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        headers.update(kwargs.pop("headers", {}) or {})
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            transport=self.transport,
            auth=(self.shop_id, self.secret_key),
            headers=headers,
        ) as client:
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.ConnectTimeout as exc:
                raise YooKassaError("YooKassa connection timed out") from exc
            except httpx.ReadTimeout as exc:
                raise YooKassaError("YooKassa response timed out") from exc
            except httpx.RequestError as exc:
                raise YooKassaError(f"YooKassa network error: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"description": response.text}
            message = None
            if isinstance(payload, dict):
                message = payload.get("description") or payload.get("error_description")
            raise YooKassaError(message or f"YooKassa API error {response.status_code}")
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise YooKassaError("YooKassa returned invalid JSON") from exc


def _money(amount: float) -> str:
    return f"{Decimal(str(amount)).quantize(Decimal('0.01'))}"


def _map_status(payload: object) -> PaymentStatus:
    if isinstance(payload, dict) and payload.get("paid") is True:
        return PaymentStatus.SUCCEEDED
    status = str(payload.get("status") if isinstance(payload, dict) else payload or "").lower()
    if status == "succeeded":
        return PaymentStatus.SUCCEEDED
    if status == "canceled":
        return PaymentStatus.CANCELLED
    if status in {"failed", "error"}:
        return PaymentStatus.FAILED
    return PaymentStatus.PENDING
