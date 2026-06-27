"""Admin rights filter tests."""
from __future__ import annotations

from app.core.config import settings


def test_admin_ids_parsed() -> None:
    assert 111 in settings.admin_ids
    assert 222 in settings.admin_ids


def test_is_admin() -> None:
    assert settings.is_admin(111) is True
    assert settings.is_admin(999) is False
