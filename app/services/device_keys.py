"""Shared helpers for deduplicating device notifications."""
from __future__ import annotations

import hashlib


def device_seen_key(subscription_uuid: str | None, *, hwid: object = "", device_id: object = "") -> str | None:
    stable_id = str(hwid or device_id or "").strip()
    if not stable_id:
        return None
    prefix = subscription_uuid or "unknown"
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:32]
    return f"device_seen:{prefix}:{digest}"
