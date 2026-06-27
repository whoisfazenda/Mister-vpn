"""Payment provider abstraction.

Concrete payment gateways implement :class:`PaymentProvider`. The rest of the
application depends only on this interface, so a real gateway can be added
later without touching VPN/order logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.enums import PaymentStatus


@dataclass(slots=True)
class PaymentResult:
    """Result of creating a payment."""

    payment_id: str
    # URL the user opens to pay. May be a placeholder in mock mode.
    confirmation_url: str
    status: PaymentStatus
    raw: dict | None = None


@dataclass(slots=True)
class WebhookResult:
    """Normalized result of parsing a payment-provider webhook."""

    payment_id: str
    status: PaymentStatus
    order_uuid: str | None = None
    event_type: str | None = None
    raw: dict | None = None


class PaymentProvider(ABC):
    """Interface every payment gateway must implement."""

    name: str = "base"

    @abstractmethod
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
        """Create a payment and return its id + confirmation URL."""

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> PaymentStatus:
        """Poll the current status of a payment."""

    @abstractmethod
    async def handle_webhook(self, raw_body: bytes, headers: dict[str, str]) -> WebhookResult:
        """Parse and verify an inbound provider webhook into a WebhookResult."""

    async def refund(self, payment_id: str, amount: float | None = None) -> bool:
        """Refund a payment (optional). Default: not supported."""
        raise NotImplementedError("Refund is not supported by this provider")
