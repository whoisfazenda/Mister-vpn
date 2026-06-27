"""Bot entrypoint — long polling.

Wires middlewares, routers, sets bot commands and runs polling. The FastAPI
webhook service runs as a separate process (see app/main_api.py).
"""
from __future__ import annotations

import asyncio
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.deps import shutdown as deps_shutdown
from app.bot.handlers import get_main_router
from app.bot.middlewares.db import DbSessionMiddleware
from app.bot.middlewares.throttling import ThrottlingMiddleware
from app.bot.middlewares.user import UserMiddleware
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.services.device_monitor import run_device_monitor_loop
from app.services.reminders import run_subscription_reminder_loop

logger = get_logger(__name__)


async def _set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="admin", description="Админ-панель"),
        ]
    )


async def main() -> None:
    setup_logging()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN не задан. Заполните .env")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Outer middlewares (run for every update): DB session, then user.
    dp.update.outer_middleware(DbSessionMiddleware())
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    # Anti double-tap on callbacks.
    dp.callback_query.middleware(ThrottlingMiddleware())

    dp.include_router(get_main_router())

    await _set_commands(bot)
    logger.info("Bot starting (long polling). DEV_MODE=%s", settings.dev_mode)
    reminder_task = asyncio.create_task(run_subscription_reminder_loop(bot))
    device_monitor_task = asyncio.create_task(run_device_monitor_loop(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in (reminder_task, device_monitor_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await deps_shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
