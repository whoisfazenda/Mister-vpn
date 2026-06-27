"""Idempotency key generation."""
from __future__ import annotations

import uuid


def new_idempotency_key() -> str:
    return uuid.uuid4().hex


def new_uuid() -> str:
    return str(uuid.uuid4())
