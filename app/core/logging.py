"""Structured logging with secret masking.

A logging filter redacts known secret values so that API keys, the bot
token and the webhook secret can never leak into logs even if accidentally
passed to a log call.
"""
from __future__ import annotations

import logging
import sys

from app.core.config import settings

_REDACTED = "***REDACTED***"


def _secret_values() -> list[str]:
    candidates = [
        settings.bot_token,
        settings.adaptgroup_api_key,
        settings.adaptgroup_api_key_id,
        settings.adaptgroup_webhook_secret,
    ]
    # Only mask non-trivial secrets to avoid redacting empty strings everywhere.
    return [c for c in candidates if c and len(c) >= 6]


class SecretMaskingFilter(logging.Filter):
    """Replaces any occurrence of known secrets in the formatted message."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets = _secret_values()

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            redacted = msg
            for secret in self._secrets:
                if secret in redacted:
                    redacted = redacted.replace(secret, _REDACTED)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        return True


def setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    handler.addFilter(SecretMaskingFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Tame noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
