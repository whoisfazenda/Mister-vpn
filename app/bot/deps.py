"""Shared bot dependencies (singletons used across handlers).

A single AdaptGroup client and payment provider live for the bot's lifetime.
"""
from __future__ import annotations

from app.clients.adaptgroup import AdaptGroupVPNClient, build_client
from app.services.payments.base import PaymentProvider
from app.services.payments.factory import get_payment_provider

_client: AdaptGroupVPNClient | None = None


def get_client() -> AdaptGroupVPNClient:
    global _client
    if _client is None:
        _client = build_client()
    return _client


def get_payments() -> PaymentProvider:
    return get_payment_provider()


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
