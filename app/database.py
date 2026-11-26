from __future__ import annotations

import logging
import asyncio
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
    db_url = _settings.async_database_url
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


def ensure_production_database() -> None:
    """Reject non-persistent or unsupported databases in production."""
    backend = engine.url.get_backend_name()
    if (
        _settings.environment == "production"
        and backend != "postgresql"
        and not _settings.allow_ephemeral_database
    ):
        raise RuntimeError(
            "Production requires a persistent PostgreSQL DATABASE_URL; "
            f"configured backend is {backend!r}. SQLite is only allowed "
            "with ALLOW_EPHEMERAL_DATABASE=true for tests."
        )


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
    """Run migrations and initialize required singleton rows."""
    ensure_production_database()
    from app.models import Base, BotSettings
    from sqlalchemy import select

    # Alembic uses a synchronous command API, while the app uses async SQLAlchemy.
    # Run it in a worker thread so startup does not try to nest event loops.
    _enable_sqlite_foreign_keys()
    await asyncio.to_thread(_run_migrations)

    async with async_session_factory() as session:
        # Инициализируем BotSettings если нет
        result = await session.execute(select(BotSettings).where(BotSettings.id == 1))
        settings = result.scalar_one_or_none()
        if not settings:
            settings = BotSettings(id=1)
            session.add(settings)
            await session.commit()
            logging.getLogger(__name__).info("Инициализирована таблица BotSettings")


def _run_migrations() -> None:
    """Apply Alembic migrations, including to databases created by create_all."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))

    # The first versions of this app used create_all and had no alembic_version.
    # Stamp that known schema before applying later migrations; otherwise Alembic
    # would try to recreate already existing tables.
    migration_url = _settings.async_database_url
    if not migration_url:
        db_path = root / "tatu_bot.db"
        migration_url = f"sqlite+aiosqlite:///{db_path}"
    config.set_main_option("sqlalchemy.url", migration_url)

    # asyncpg is the only PostgreSQL driver installed by the application.
    # Inspect through the async engine as well; converting to a sync URL would
    # require an uninstalled psycopg2/psycopg driver during every startup.
    async def existing_tables() -> set[str]:
        inspection_engine = create_async_engine(migration_url, poolclass=None)
        try:
            async with inspection_engine.connect() as connection:
                return await connection.run_sync(
                    lambda sync_connection: set(
                        inspect(sync_connection).get_table_names()
                    )
                )
        finally:
            await inspection_engine.dispose()

    tables = asyncio.run(existing_tables())
    if tables and "alembic_version" not in tables:
        command.stamp(config, "001")
    command.upgrade(config, "head")
