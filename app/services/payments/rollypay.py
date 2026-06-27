"""RollyPay payment provider.

Docs: https://docs.rollypay.io
"""
from __future__ import annotations

import hmac
import json
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import uuid4

import httpx

from app.core.config import settings
from app.core.enums import PaymentStatus
from app.services.payments.base import PaymentProvider, PaymentResult, WebhookResult


class RollyPayError(Exception):
    """Raised when RollyPay returns an error or a malformed response."""


class RollyPayProvider(PaymentProvider):
    name = "rollypay"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        signing_secret: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.rollypay_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.rollypay_api_key
        self.signing_secret = (
            signing_secret if signing_secret is not None else settings.rollypay_signing_secret
        )
        self.timeout = timeout or settings.rollypay_timeout
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
        if not self.api_key:
            raise RollyPayError("ROLLYPAY_API_KEY is not configured")

        payload: dict[str, Any] = {
            "amount": _money(amount),
            "payment_currency": currency,
            "order_id": order_uuid,
            "description": description,
            "metadata": {"idempotency_key": idempotency_key},
        }
        selected_method = payment_method or settings.rollypay_payment_method
        if selected_method:
            payload["payment_method"] = selected_method
        if settings.rollypay_terminal_id:
            payload["terminal_id"] = settings.rollypay_terminal_id
        if settings.rollypay_success_redirect_url:
            payload["success_redirect_url"] = settings.rollypay_success_redirect_url
        if settings.rollypay_fail_redirect_url:
            payload["fail_redirect_url"] = settings.rollypay_fail_redirect_url

        data = await self._request("POST", "/api/v1/payments", json=payload)
        payment_id = str(data.get("payment_id") or "")
        pay_url = str(data.get("pay_url") or "")
        if not payment_id or not pay_url:
            raise RollyPayError("RollyPay did not return payment_id/pay_url")
        return PaymentResult(
            payment_id=payment_id,
            confirmation_url=pay_url,
            status=_map_status(data.get("status")),
            raw=data,
        )

    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        if not payment_id:
            return PaymentStatus.PENDING
        data = await self._request("GET", f"/api/v1/payments/{payment_id}")
        return _map_status(data.get("status"))

    async def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        signature = _header(headers, "x-signature")
        timestamp = _header(headers, "x-timestamp")
        if not self.verify_signature(raw_body, timestamp, signature):
            raise RollyPayError("Invalid RollyPay webhook signature")

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RollyPayError("Invalid RollyPay webhook JSON") from exc

        payment_id = str(payload.get("payment_id") or "")
        order_uuid = str(payload.get("order_id") or "") or None
        return WebhookResult(
            payment_id=payment_id,
            order_uuid=order_uuid,
            event_type=str(payload.get("event_type") or ""),
            status=_map_status(payload.get("status")),
            raw=payload,
        )

    def verify_signature(
        self, raw_body: bytes, timestamp: str | None, signature: str | None
    ) -> bool:
        if not self.signing_secret or not timestamp or not signature:
            return False
        signed = timestamp.encode("utf-8") + b"." + raw_body
        expected = hmac.new(
            self.signing_secret.encode("utf-8"), signed, sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            transport=self.transport,
            headers={
                "X-API-Key": self.api_key,
                "X-Nonce": str(uuid4()),
                "Content-Type": "application/json",
            },
        ) as client:
            response = await client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": response.text}
            message = payload.get("error") if isinstance(payload, dict) else None
            raise RollyPayError(message or f"RollyPay API error {response.status_code}")
        try:
            return response.json() if response.content else {}
        except ValueError as exc:
            raise RollyPayError("RollyPay returned invalid JSON") from exc


def _money(amount: float) -> str:
    return f"{Decimal(str(amount)).quantize(Decimal('0.01'))}"


def _map_status(value: object) -> PaymentStatus:
    status = str(value or "").lower()
    if status == "paid":
        return PaymentStatus.SUCCEEDED
    if status in {"canceled", "expired", "chargeback", "refunded"}:
        return PaymentStatus.CANCELLED
    if status in {"failed", "error"}:
        return PaymentStatus.FAILED
    return PaymentStatus.PENDING


def _header(headers: dict[str, str], name: str) -> str | None:
    lower = name.lower()
    for key, value in headers.items():
        if key.lower() == lower:
            return value
    return None
