from __future__ import annotations

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


async def init_db():
    """Инициализация БД: создание таблиц и начальных данных."""
    from app.models import Base, BotSettings
    from sqlalchemy import select, event
    from sqlalchemy.engine import Engine

    async with async_session_factory() as session:
        # Создаём таблицы
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Инициализируем BotSettings если нет
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings = result.scalar_one_or_none()
        if not settings:
            settings = BotSettings(id=1)
            session.add(settings)
            await session.commit()
            print("✅ Инициализирована таблица BotSettings")
