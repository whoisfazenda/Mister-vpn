"""Handlers package — aggregates all routers in registration order."""
from aiogram import Router

from app.bot.handlers import (
    admin,
    balance,
    buy,
    devices,
    menu,
    my_vpn,
    profile,
    renew,
    traffic,
    trial,
    upgrade,
)


def get_main_router() -> Router:
    root = Router(name="root")
    # Admin first so its filters take precedence for admin users.
    root.include_router(admin.router)
    root.include_router(menu.router)
    root.include_router(balance.router)
    root.include_router(profile.router)
    root.include_router(trial.router)
    root.include_router(buy.router)
    root.include_router(my_vpn.router)
    root.include_router(devices.router)
    root.include_router(renew.router)
    root.include_router(upgrade.router)
    root.include_router(traffic.router)
    return root
