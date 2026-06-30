"""Shared helpers for handlers: AdaptGroup error → friendly text, admin alerts."""
from __future__ import annotations

from app.bot import texts
from app.bot.premium_emoji import pe
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
        return f"{pe('warning')} Сейчас оформить не получилось. Мы уже разбираемся, попробуйте позже."
    if isinstance(exc, (AdaptGroupUnavailable, AdaptGroupNetworkError)):
        return f"{pe('settings')} Сервис временно недоступен. Попробуйте через несколько минут."
    if isinstance(exc, (AdaptGroupAuthError, AdaptGroupForbidden, AdaptGroupError)):
        return texts.ERROR_GENERIC
    if isinstance(exc, RollyPayError):
        return f"{pe('warning')} Не удалось создать или проверить платеж. Попробуйте позже или напишите в поддержку."
    if isinstance(exc, YooKassaError):
        return f"{pe('warning')} Не удалось создать или проверить платеж. Попробуйте позже или напишите в поддержку."
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
