"""Pterodactyl entrypoint.

The Python egg runs ``python ${PY_FILE}``, so module commands like
``python -m alembic upgrade head && python -m app.main_bot`` cannot be placed
directly into PY_FILE. This file performs the same steps from Python:
run database migrations first, then start the Telegram bot.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent
LOCAL_SITE = ROOT / ".local" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"

for path in (ROOT, LOCAL_SITE):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def import_bot_main():
    try:
        return importlib.import_module("app.main_bot").main
    except ModuleNotFoundError as exc:
        print("Could not import app.main_bot.", file=sys.stderr)
        print(f"Project root: {ROOT}", file=sys.stderr)
        print(f"Root exists: {ROOT.exists()}", file=sys.stderr)
        print(f"app dir exists: {(ROOT / 'app').exists()}", file=sys.stderr)
        if ROOT.exists():
            names = ", ".join(sorted(p.name for p in ROOT.iterdir())[:50])
            print(f"Root files: {names}", file=sys.stderr)
        print("sys.path:", file=sys.stderr)
        for item in sys.path:
            print(f"  - {item}", file=sys.stderr)
        raise exc


def run_migrations() -> None:
    config = Config("alembic.ini")
    command.upgrade(config, "head")


if __name__ == "__main__":
    run_migrations()
    main = import_bot_main()
    asyncio.run(main())
