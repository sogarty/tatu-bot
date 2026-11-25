from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

# Определяем URL базы данных
# Если DB_URL не указана, используем SQLite для локальной разработки
if _settings.database_url:
    db_url = _settings.database_url
else:
    # SQLite по умолчанию
    db_path = Path(__file__).parent.parent / "tatu_bot.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(
    db_url,
    echo=_settings.environment == "development",
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session


async def get_async_engine():
    return engine


def _enable_sqlite_foreign_keys() -> None:
    """Включает внешние ключи в SQLite.

    По умолчанию SQLite их НЕ проверяет, поэтому ondelete=CASCADE
    и ссылочная целостность молча игнорируются.
    Для PostgreSQL ничего не делаем — там FK включены всегда.
    """
    from sqlalchemy import event

    if not engine.url.get_backend_name().startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


async def init_db():
    """Инициализация БД: создание таблиц и начальных данных."""
    from app.models import Base, BotSettings
    from sqlalchemy import select

    # ВАЖНО: слушатель ставим до первого подключения, иначе PRAGMA
    # не применится к уже открытому соединению.
    _enable_sqlite_foreign_keys()

    async with async_session_factory() as session:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Инициализируем BotSettings если нет
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings = result.scalar_one_or_none()
        if not settings:
            settings = BotSettings(id=1)
            session.add(settings)
            await session.commit()
            logging.getLogger(__name__).info("Инициализирована таблица BotSettings")
