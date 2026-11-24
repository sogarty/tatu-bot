"""Telegram бот — инициализация и запуск."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import get_settings
from app.bot.dp import setup_registrars

logger = logging.getLogger(__name__)
settings = get_settings()


def create_bot() -> Bot:
    """Создаёт экземпляр бота."""
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Создаёт Dispatcher и настраивает хендлеры."""
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    setup_registrars(dp)
    return dp


async def main() -> None:
    """Точка входа для бота (longpoll)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = create_bot()
    dp = create_dispatcher()

    logger.info("Бот запущен в режиме longpoll!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен (KeyboardInterrupt)")
    except SystemExit:
        logger.info("Бот остановлен (SystemExit)")
    except Exception as e:
        logger.critical(f"Бот упал с ошибкой: {e}", exc_info=True)
        sys.exit(1)
