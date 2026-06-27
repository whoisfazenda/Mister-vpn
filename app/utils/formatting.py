"""Formatting helpers for user-facing text."""
from __future__ import annotations

import html
from datetime import datetime, timezone


def escape(text: object) -> str:
    """HTML-escape arbitrary (possibly user-provided) text for safe output."""
    return html.escape(str(text), quote=False)


def format_traffic(bytes_or_none: int | float | None) -> str:
    """Format a traffic value in bytes as a human GB string, or 'безлимит'.

    ``None`` (or a falsy zero meaning "no limit") renders as unlimited.
    """
    if bytes_or_none is None:
        return "безлимит"
    try:
        value = float(bytes_or_none)
    except (TypeError, ValueError):
        return "безлимит"
    if value <= 0:
        return "безлимит"
    gb = value / (1024 ** 3)
    if gb >= 100:
        return f"{gb:.0f} ГБ"
    return f"{gb:.1f} ГБ"


def format_gb_used(used: int | float | None, limit: int | float | None) -> str:
    """Format 'used X ГБ из Y ГБ' or unlimited."""
    if limit is None or float(limit) <= 0:
        return "безлимитный"
    used_gb = float(used or 0) / (1024 ** 3)
    limit_gb = float(limit) / (1024 ** 3)
    return f"{used_gb:.1f} ГБ из {limit_gb:.1f} ГБ"


def format_price(amount: float | int | None, currency: str) -> str:
    if amount is None:
        return "—"
    if float(amount).is_integer():
        return f"{int(amount)} {currency}"
    return f"{amount:.2f} {currency}"


def format_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


def format_days(days: int) -> str:
    """Russian pluralization for days."""
    d = abs(days) % 100
    d1 = d % 10
    if 11 <= d <= 14:
        word = "дней"
    elif d1 == 1:
        word = "день"
    elif 2 <= d1 <= 4:
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"
