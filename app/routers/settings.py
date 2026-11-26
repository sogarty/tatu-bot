"""Bot settings management."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin_only
from app.database import get_db
from app.models import BotSettings
from app.schemas import BotSettingsOut, BotSettingsUpdate

router = APIRouter(tags=["settings"])


@router.get("/settings", response_model=BotSettingsOut)
async def get_settings(
    session: AsyncSession = Depends(get_db),
):
    """Получить настройки бота."""
    result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = BotSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


@router.put("/settings", response_model=BotSettingsOut)
async def update_settings(
    data: BotSettingsUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Обновить настройки бота."""
    result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = BotSettings(id=1)
        session.add(settings)
        await session.flush()

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(settings, field, value)

    await session.commit()
    # После commit объект «просрочен»: обращение к updated_at вызвало бы
    # ленивую подгрузку и упало бы с MissingGreenlet. Перечитываем явно.
    await session.refresh(settings)
    return settings
