"""Pterodactyl entrypoint.

The Python egg runs ``python ${PY_FILE}``, so module commands like
``python -m alembic upgrade head && python -m app.main_bot`` cannot be placed
directly into PY_FILE. This file performs the same steps from Python:
run database migrations first, then start the Telegram bot.
"""
from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from app.main_bot import main


def run_migrations() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


if __name__ == "__main__":
    run_migrations()
    asyncio.run(main())
