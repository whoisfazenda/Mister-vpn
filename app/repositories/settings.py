"""App settings repository."""
from __future__ import annotations

from sqlalchemy import select

from app.db.models.app_setting import AppSetting
from app.repositories.base import BaseRepository


class SettingsRepository(BaseRepository):
    async def get(self, key: str) -> str | None:
        res = await self.session.execute(
            select(AppSetting.value).where(AppSetting.key == key)
        )
        return res.scalar_one_or_none()

    async def set(self, key: str, value: str | None, description: str | None = None) -> None:
        res = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        obj = res.scalar_one_or_none()
        if obj is None:
            self.session.add(AppSetting(key=key, value=value, description=description))
        else:
            obj.value = value
            if description is not None:
                obj.description = description
