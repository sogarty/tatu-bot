"""Здоровье приложения: GET /api/v1/health.

Отвечает не только «жив ли процесс», но и на вопросы, которые реально
ломают работу: подключена ли база, инициализирован ли бот, знает ли сервер
id мастера. Без этого сбой выглядел как «приложение не работает», а причина
оставалась невидимой.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health", summary="Проверка здоровья")
async def health(session: AsyncSession = Depends(get_db)):
    """Проверка доступности сервиса, БД и готовности бота."""
    settings = get_settings()

    # Драйвер базы: sqlite = данные пропадут при перезапуске,
    # postgresql = данные сохраняются. Это ключевая информация.
    try:
        backend = session.bind.url.get_backend_name()
    except Exception:  # pragma: no cover
        backend = "unknown"
    persistent = not backend.startswith("sqlite")

    # Готов ли бот принимать сообщения (в webhook-режиме он создаётся на старте).
    bot_ready = False
    try:
        from app.main import bot as running_bot

        bot_ready = running_bot is not None
    except Exception:  # pragma: no cover
        bot_ready = False

    payload = {
        "status": "ok",
        "database": "connected",
        "database_backend": backend,
        "data_persistent": persistent,
        "bot_ready": bot_ready,
        "master_configured": settings.master_tg_id > 0,
        "mode": settings.mode,
    }

    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "database": "unavailable",
                "detail": str(e)[:200],
            },
        )

    return payload