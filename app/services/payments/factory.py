"""Payment provider factory.

A single shared instance is returned per provider name so in-memory state of
the mock provider survives across handler calls within one process.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.payments.base import PaymentProvider
from app.services.payments.mock import MockPaymentProvider
from app.services.payments.rollypay import RollyPayProvider
from app.services.payments.yookassa import YooKassaProvider


@lru_cache
def get_payment_provider(provider_name: str | None = None) -> PaymentProvider:
    provider = (provider_name or settings.payment_provider).lower().strip()
    if provider == "mock":
        return MockPaymentProvider()
    if provider == "rollypay":
        return RollyPayProvider()
    if provider == "yookassa":
        return YooKassaProvider()
    raise ValueError(
        f"Unknown PAYMENT_PROVIDER='{provider}'. Available: mock, rollypay, yookassa."
    )
