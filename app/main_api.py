"""FastAPI webhook service entrypoint.

Runs as a separate process from the bot. Holds its own Bot instance (for
sending user notifications) and a shared AdaptGroup client.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from fastapi import FastAPI

from app.api.routes import subscription_page, webhooks
from app.clients.adaptgroup import build_client
from app.core.config import settings
from app.core.logging import get_logger, setup_logging

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    app.state.bot = (
        Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        if settings.bot_token
        else None
    )
    app.state.adaptgroup_client = build_client()
    await app.state.adaptgroup_client.start()
    logger.info("Webhook API started")
    try:
        yield
    finally:
        await app.state.adaptgroup_client.close()
        if app.state.bot is not None:
            await app.state.bot.session.close()
        logger.info("Webhook API stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="VPN Bot Webhooks", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(webhooks.router)
    app.include_router(subscription_page.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main_api:app",
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level=settings.log_level.lower(),
    )
