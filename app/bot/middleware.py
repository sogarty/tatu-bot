"""Middleware для внедрения DB session в handlers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory


class DatabaseMiddleware(BaseMiddleware):
    """Добавляет AsyncSession в event handler kwargs."""

    async def __call__(
        self,
        handler: Callable[
            [Any, dict[str, Any]], Awaitable[Any]
        ],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
