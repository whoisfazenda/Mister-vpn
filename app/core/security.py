"""Security helpers: webhook signature verification and value masking."""
from __future__ import annotations

import hashlib
import hmac


def compute_signature(secret: str, raw_body: bytes) -> str:
    """HMAC-SHA256 of the raw request body, hex-encoded."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(secret: str, raw_body: bytes, received: str | None) -> bool:
    """Constant-time comparison of expected vs received signature.

    Tolerates an optional ``sha256=`` prefix on the received header value.
    """
    if not secret or not received:
        return False
    received = received.strip()
    if received.lower().startswith("sha256="):
        received = received[len("sha256="):]
    expected = compute_signature(secret, raw_body)
    return hmac.compare_digest(expected, received)


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Mask a secret for safe display (e.g. ``abcd…``). Never returns the full value."""
    if not value:
        return "—"
    if len(value) <= visible:
        return "*" * len(value)
    return f"{value[:visible]}{'…'}{'*' * 4}"
