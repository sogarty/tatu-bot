"""Сборка aiogram Dispatcher: роутеры, middleware, обработчик ошибок."""

from __future__ import annotations

import logging

from aiogram import Dispatcher
from aiogram.types import ErrorEvent

from app.bot.handlers import client
from app.bot.middleware import DatabaseMiddleware

logger = logging.getLogger(__name__)


def setup_registrars(dp: Dispatcher) -> None:
    """Подключает middleware и роутеры.

    В боте намеренно только клиентский роутер: кабинет мастера живёт
    в Mini App, а не в чате. Поэтому admin-роутер здесь не регистрируется —
    это убирает и дубли обработчиков, и конфликт «ловушки текста» с /admin.
    """

    # ── Middleware с сессией БД ───────────────────────────────────────────
    db_middleware = DatabaseMiddleware()
    dp.message.middleware(db_middleware)
    dp.callback_query.middleware(db_middleware)

    # ── Клиентские обработчики ────────────────────────────────────────────
    client.register_handlers(dp)

    # ── Обработчик необработанных ошибок ──────────────────────────────────
    @dp.errors()
    async def error_handler(event: ErrorEvent) -> bool:
        """Логирует ошибку и подтверждает обработку.

        В aiogram 3 обработчик получает объект ErrorEvent, из которого
        берётся исключение. Второй аргумент (exception) в контексте
        отсутствует — именно из-за него прежний код падал с TypeError,
        и ошибка оставалась незамеченной.
        """
        exc = event.exception
        update = event.update

        logger.error(
            "Необработанная ошибка: %s: %s (update_id=%s)",
            type(exc).__name__,
            exc,
            getattr(update, "update_id", "?"),
            exc_info=exc,
        )
        return True