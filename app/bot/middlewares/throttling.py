"""Throttling middleware — anti double-tap on callbacks.

Drops callback queries that arrive faster than a small interval for the same
(user, callback_data) pair. Protects against duplicate provisioning triggered
by impatient double taps. In-memory, per-process (sufficient for long polling).
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, interval: float = 0.7) -> None:
        self.interval = interval
        self._last: dict[tuple[int, str], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            key = (event.from_user.id, event.data or "")
            now = time.monotonic()
            last = self._last.get(key, 0.0)
            if now - last < self.interval:
                await event.answer()  # ack silently, ignore
                return None
            self._last[key] = now
            # Opportunistic cleanup to bound memory.
            if len(self._last) > 10000:
                cutoff = now - 60
                self._last = {k: v for k, v in self._last.items() if v > cutoff}
        return await handler(event, data)
