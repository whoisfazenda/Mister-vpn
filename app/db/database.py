"""Async SQLAlchemy engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=not settings.database_url.startswith("mysql+aiomysql://"),
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine,
    expire_on_commit=False,
    autoflush=False,
)


def get_engine() -> AsyncEngine:
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session (FastAPI dependency / manual usage)."""
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    await _engine.dispose()
