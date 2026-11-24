"""aiogram Dispatcher setup — регистрация handlers и middleware."""

from __future__ import annotations

from aiogram import Dispatcher

from app.bot.middleware import DatabaseMiddleware
from app.bot.keyboards import register_kb_callbacks
from app.bot.handlers import client, request as request_handlers, admin


def setup_registrars(dp: Dispatcher) -> None:
    """Регистрирует все обработчики и middleware на диспетчере."""

    # Middleware для DB session
    db_middleware = DatabaseMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # Регистрация callback обработчиков клавиатур
    register_kb_callbacks(dp)

    # ─── Client handlers ───
    client.register_handlers(dp)

    # ─── Request creation handlers ───
    request_handlers.register_handlers(dp)

    # ─── Admin handlers ───
    admin.register_handlers(dp)

    # ─── Error handler ───
    @dp.errors()
    async def error_handler(exception: Exception):
        from aiogram.types import ErrorEvent
        event = ErrorEvent(exception=exception)
        import logging
        logging.getLogger(__name__).error(
            "Unhandled error: %s", exception, exc_info=True
        )
