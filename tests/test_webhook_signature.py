"""Webhook signature verification tests."""
from __future__ import annotations

from app.core.security import compute_signature, verify_webhook_signature

SECRET = "test-webhook-secret"


def test_valid_signature() -> None:
    body = b'{"event":"subs.created","data":{}}'
    sig = compute_signature(SECRET, body)
    assert verify_webhook_signature(SECRET, body, sig) is True


def test_valid_signature_with_prefix() -> None:
    body = b'{"event":"subs.created"}'
    sig = compute_signature(SECRET, body)
    assert verify_webhook_signature(SECRET, body, f"sha256={sig}") is True


def test_invalid_signature() -> None:
    body = b'{"event":"subs.created"}'
    assert verify_webhook_signature(SECRET, body, "deadbeef") is False


def test_tampered_body() -> None:
    body = b'{"event":"subs.created"}'
    sig = compute_signature(SECRET, body)
    tampered = b'{"event":"subs.expired"}'
    assert verify_webhook_signature(SECRET, tampered, sig) is False


def test_missing_signature() -> None:
    assert verify_webhook_signature(SECRET, b"{}", None) is False


def test_empty_secret() -> None:
    assert verify_webhook_signature("", b"{}", "anything") is False
