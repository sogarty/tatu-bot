from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot
    bot_token: str
    mode: Literal["longpoll", "webhook"] = "longpoll"
    webapp_url: str | None = None

    # Master / Admin
    master_tg_id: int = 0
    admin_api_key: str = ""

    # Webhook
    webhook_url: str | None = None

    # Database
    # Для PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname
    # Для SQLite (по умолчанию): оставь пустым
    database_url: str = ""

    # Redis (optional fallback)
    redis_url: str | None = None

    # Environment
    environment: Literal["development", "production"] = "development"

    # === Новые поля для Render-деплоя ===
    # Базовый URL для webhook (например, https://mybot.onrender.com)
    webhook_base_url: str = ""
    # Секретный токен для проверки подлинности webhook-уведомлений
    webhook_secret: str = ""
    # Разрешённые источники CORS (через запятую, например https://myapp.pages.dev)
    allowed_origins: str = "*"

    @property
    def db_url_sync(self) -> str:
        """Return sync URL for Alembic."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def allowed_origins_list(self) -> list[str]:
        """Разбирает allowed_origins в список."""
        if self.allowed_origins == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
