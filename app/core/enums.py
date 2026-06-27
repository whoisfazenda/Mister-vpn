"""Enumerations shared across layers."""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class OrderType(StrEnum):
    NEW_SUBSCRIPTION = "new_subscription"
    RENEW = "renew"
    RENEW_CUSTOM = "renew_custom"
    UPGRADE = "upgrade"
    TRAFFIC = "traffic"
    BALANCE_TOPUP = "balance_topup"


class OrderStatus(StrEnum):
    PENDING = "pending"          # создан, ждёт оплату
    PAID = "paid"                # оплата подтверждена, VPN ещё не выдан
    PROVISIONING = "provisioning"  # идёт обращение к AdaptGroup (lock)
    COMPLETED = "completed"      # VPN выдан/применён
    FAILED = "failed"            # ошибка выдачи (деньги уже списаны — нужна ручная проверка)
    CANCELLED = "cancelled"      # отменён пользователем до оплаты


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELLED = "cancelled"
    FAILED = "failed"


class WebhookProcessResult(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    ERROR = "error"


# Статусы заказа, при которых выдача VPN ещё может быть безопасно повторена
RETRYABLE_ORDER_STATUSES = frozenset({OrderStatus.PAID, OrderStatus.FAILED})
