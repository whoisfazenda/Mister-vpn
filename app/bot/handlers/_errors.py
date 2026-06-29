"""Shared helpers for handlers: AdaptGroup error → friendly text, admin alerts."""
from __future__ import annotations

from app.bot import texts
from app.clients.adaptgroup import (
    AdaptGroupAuthError,
    AdaptGroupBadRequest,
    AdaptGroupError,
    AdaptGroupForbidden,
    AdaptGroupInsufficientFunds,
    AdaptGroupNetworkError,
    AdaptGroupNotFound,
    AdaptGroupRateLimited,
    AdaptGroupUnavailable,
    AdaptGroupValidationError,
)
from app.services.payments.rollypay import RollyPayError
from app.services.payments.yookassa import YooKassaError


def friendly_error(exc: Exception) -> str:
    """Map an AdaptGroup/other exception to a user-safe message (no internals)."""
    if isinstance(exc, AdaptGroupRateLimited):
        return texts.ERROR_RATE_LIMIT
    if isinstance(exc, AdaptGroupNotFound):
        return texts.ERROR_NOT_FOUND
    if isinstance(exc, (AdaptGroupBadRequest, AdaptGroupValidationError)):
        return texts.ERROR_BAD_STATE
    if isinstance(exc, AdaptGroupInsufficientFunds):
        # Do not reveal integration balance details to the user.
        return "⚠️ Сейчас оформить не получилось. Мы уже разбираемся, попробуйте позже."
    if isinstance(exc, (AdaptGroupUnavailable, AdaptGroupNetworkError)):
        return "🛠 Сервис временно недоступен. Попробуйте через несколько минут."
    if isinstance(exc, (AdaptGroupAuthError, AdaptGroupForbidden, AdaptGroupError)):
        return texts.ERROR_GENERIC
    if isinstance(exc, RollyPayError):
        return "⚠️ Не удалось создать или проверить платеж. Попробуйте позже или напишите в поддержку."
    if isinstance(exc, YooKassaError):
        return "\u26a0\ufe0f \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0441\u043e\u0437\u0434\u0430\u0442\u044c \u0438\u043b\u0438 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043f\u043b\u0430\u0442\u0435\u0436 \u0447\u0435\u0440\u0435\u0437 \u0421\u0411\u041f #2. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435 \u0438\u043b\u0438 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 \u0432 \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0443."
    return texts.ERROR_GENERIC


def needs_admin_alert(exc: Exception) -> str | None:
    """Return an admin-facing alert message for critical issues, else None."""
    if isinstance(exc, AdaptGroupInsufficientFunds):
        return "Недостаточно средств на балансе интеграции AdaptGroup. Пополните баланс."
    if isinstance(exc, AdaptGroupAuthError):
        return "Проблема с API-ключом AdaptGroup (401). Проверьте конфигурацию."
    if isinstance(exc, AdaptGroupForbidden):
        return "AdaptGroup вернул 403 — тариф не принадлежит интеграции."
    if isinstance(exc, AdaptGroupUnavailable):
        return "AdaptGroup API недоступен (503)."
    if isinstance(exc, AdaptGroupNetworkError):
        return "Сетевая ошибка при обращении к AdaptGroup — проверьте связность."
    return None
