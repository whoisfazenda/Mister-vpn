"""Pytest fixtures: in-memory SQLite async DB and helpers."""
from __future__ import annotations

import os

# Ensure settings load without a real .env (set required-ish defaults).
os.environ.setdefault("BOT_TOKEN", "test:token")
os.environ.setdefault("ADMIN_IDS", "111,222")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ADAPTGROUP_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("ADAPTGROUP_API_KEY", "test-api-key-123456")
os.environ.setdefault("ADAPTGROUP_API_KEY_ID", "integration-1")
os.environ.setdefault("DEV_MODE", "true")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.database import Base
import app.db.models  # noqa: F401  (populate metadata)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
