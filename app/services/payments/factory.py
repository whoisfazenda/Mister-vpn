"""Payment provider factory — selects the provider from settings.

A single shared instance is returned so that the MockPaymentProvider's
in-memory state survives across handler calls within a process.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.services.payments.base import PaymentProvider
from app.services.payments.mock import MockPaymentProvider
from app.services.payments.rollypay import RollyPayProvider


@lru_cache
def get_payment_provider() -> PaymentProvider:
    provider = settings.payment_provider.lower().strip()
    if provider == "mock":
        return MockPaymentProvider()
    if provider == "rollypay":
        return RollyPayProvider()
    raise ValueError(
        f"Неизвестный PAYMENT_PROVIDER='{provider}'. Доступно: mock, rollypay."
    )
