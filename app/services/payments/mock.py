"""Mock payment provider for development.

Creates a payment in PENDING state. Payments are NOT auto-confirmed. Marking a
mock payment as paid is only possible via the admin dev-mode action, keeping
test "payments" deliberate and traceable. Confirmation is stored in-memory.
"""
from __future__ import annotations

from app.core.enums import PaymentStatus
from app.core.logging import get_logger
from app.services.payments.base import (
    PaymentProvider,
    PaymentResult,
    WebhookResult,
)

logger = get_logger(__name__)


class MockPaymentProvider(PaymentProvider):
    name = "mock"

    def __init__(self) -> None:
        # payment_id -> status (process-local; for dev only)
        self._statuses: dict[str, PaymentStatus] = {}

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
        payment_id = f"mock_{idempotency_key}"
        self._statuses[payment_id] = PaymentStatus.PENDING
        # A harmless placeholder URL. A real provider returns its hosted page.
        confirmation_url = f"https://example.com/mock-pay/{payment_id}"
        logger.info("Mock payment created for order %s (%s %s)", order_uuid, amount, currency)
        return PaymentResult(
            payment_id=payment_id,
            confirmation_url=confirmation_url,
            status=PaymentStatus.PENDING,
        )

    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        return self._statuses.get(payment_id, PaymentStatus.PENDING)

    async def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        # The mock provider does not receive real webhooks.
        raise NotImplementedError("MockPaymentProvider does not handle webhooks")

    # ── dev helpers ──────────────────────────────────────────
    def mark_paid(self, payment_id: str) -> None:
        """Dev-only: force a mock payment to SUCCEEDED."""
        self._statuses[payment_id] = PaymentStatus.SUCCEEDED
