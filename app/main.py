"""FastAPI приложение + uvicorn entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers.health import router as health_router
from app.routers.requests import router as requests_router
from app.routers.slots import router as slots_router
from app.routers.settings import router as settings_router
from app.routers.admin import router as admin_router
from app.routers.portfolio import router as portfolio_router

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── Глобальные объекты бота ────────────────────────────────────────────────

bot: Bot | None = None
dp = None  # Dispatcher (импортируется лениво)
webhook_ready = False
webhook_error: str | None = None


def _create_bot() -> Bot:
    """Создаёт экземпляр бота (один раз)."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _create_dp():
    """Создаёт Dispatcher и настраивает хендлеры (один раз)."""
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage

    storage = MemoryStorage()
    local_dp = Dispatcher(storage=storage)
    from app.bot.dp import setup_registrars
    setup_registrars(local_dp)
    return local_dp


def _validate_production_config() -> None:
    """Fail early when production cannot receive Telegram updates safely."""
    if settings.environment != "production":
        return

    missing = []
    if not settings.bot_token or settings.bot_token.startswith("test_"):
        missing.append("BOT_TOKEN")
    if settings.master_tg_id <= 0:
        missing.append("MASTER_TG_ID")
    if settings.mode == "webhook":
        if not settings.webhook_base_url.startswith("https://"):
            missing.append("WEBHOOK_BASE_URL (HTTPS)")
        if not settings.webhook_secret:
            missing.append("WEBHOOK_SECRET")
    if not settings.webapp_url or not settings.webapp_url.startswith("https://"):
        missing.append("WEBAPP_URL (HTTPS)")
    if not settings.allowed_origins_list or settings.allowed_origins_list == ["*"]:
        missing.append("ALLOWED_ORIGINS (exact origin)")
    if missing:
        raise RuntimeError(
            "Production configuration is incomplete: " + ", ".join(missing)
        )


async def _set_webhook(bot_instance: Bot, url: str, secret: str) -> None:
    """Асинхронно устанавливает webhook с повторами при TelegramRetryAfter."""
    global webhook_ready, webhook_error
    max_retries = 5
    webhook_ready = False
    webhook_error = None
    for attempt in range(1, max_retries + 1):
        try:
            await bot_instance.set_webhook(
                url,
                secret_token=secret,
                # ВАЖНО: НЕ сбрасываем очередь. На бесплатном хостинге сервис
                # засыпает и при пробуждении заново вызывает set_webhook.
                # С drop_pending_updates=True сообщения, отправленные пока
                # сервис просыпался (например, первое "/start"), УДАЛЯЛИСЬ —
                # бот молчал, и приходилось писать команду второй раз.
                drop_pending_updates=False,
            )
            # result — True при успехе
            host = url.split("://", 1)[-1].split("/")[0] if "://" in url else url
            logger.info("Webhook установлен: %s", host)
            webhook_ready = True
            return
        except TelegramRetryAfter as e:
            wait_seconds = e.retry_after + 3
            logger.warning(
                "Telegram вернул TelegramRetryAfter (попытка %d/%d), "
                "ждём %d сек.",
                attempt, max_retries, wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
        except Exception as e:
            logger.error("Ошибка при установке webhook (попытка %d/%d): %s", attempt, max_retries, e)
            webhook_error = str(e)[:200]
            break
    if not webhook_error:
        webhook_error = "Не удалось установить webhook после повторных попыток"
    logger.error("Не удалось установить webhook после %d попыток", max_retries)


async def _init_db_and_tables() -> None:
    """Создаёт таблицы БД и начальные данные."""
    from app.database import ensure_production_database, init_db
    ensure_production_database()
    await init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    global bot, dp

    # ── startup ──────────────────────────────────────────────────────────
    logger.info("=== Точка входа FastAPI ===")
    logger.info("Режим: %s", settings.mode)
    _validate_production_config()

    # Создаём бота один раз
    bot = _create_bot()

    if settings.mode == "webhook":
        # Dispatcher нужен ВСЕГДА в webhook-режиме: без него /webhook
        # отвечает 503, и Telegram бесконечно повторяет один и тот же update.
        dp = _create_dp()

        if settings.webhook_base_url:
            webhook_url = settings.webhook_base_url.rstrip("/") + "/webhook"
            # Readiness must not report a healthy service before Telegram is
            # actually pointed at this instance. Telegram queues updates while
            # the service is starting, so waiting here is safer than exposing a
            # green but unreachable webhook.
            await _set_webhook(bot, webhook_url, settings.webhook_secret)
            if not webhook_ready:
                raise RuntimeError(webhook_error or "Webhook setup failed")
        else:
            logger.warning(
                "WEBHOOK_BASE_URL не задан — webhook не устанавливается. "
                "Бот не сможет получать сообщения."
            )

    # Инициализация БД и применение Alembic-миграций.
    try:
        await _init_db_and_tables()
    except Exception:
        logger.error("Не удалось инициализировать БД", exc_info=True)
        if settings.environment == "production":
            raise

    yield

    # ── shutdown ─────────────────────────────────────────────────────────
    if bot:
        await bot.session.close()
        logger.info("Сессия бота закрыта")
    logger.info("API shutdown complete")


app = FastAPI(
    title="Tattoo Bot API",
    version="1.0.0",
    lifespan=lifespan,
)

# ─── CORS ───────────────────────────────────────────────────────────────────
allowed = settings.allowed_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Маршруты ───────────────────────────────────────────────────────────────
app.include_router(health_router, prefix="/api/v1")
app.include_router(requests_router, prefix="/api/v1")
app.include_router(slots_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")

# ─── Mini App статика ──────────────────────────────────────────────────────
# main.py лежит в deploy/app/, а папка web — в deploy/. Отсюда parent.parent.
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

if _WEB_DIR.is_dir():

    class NoCacheStaticFiles(StaticFiles):
        """Статика Mini App с запретом кэширования.

        Telegram открывает приложение во встроенном браузере, который
        агрессивно кэширует app.js и style.css. Без этого заголовка человек
        после нашего исправления ещё долго видел бы СТАРЫЙ сломанный код —
        и любая правка «не доходила» бы до него. Для маленького приложения
        честнее всегда отдавать свежую версию.
        """

        async def get_response(self, path, scope):  # noqa: D102
            response = await super().get_response(path, scope)
            response.headers["Cache-Control"] = (
                "no-cache, no-store, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

    app.mount(
        "/app",
        NoCacheStaticFiles(directory=str(_WEB_DIR), html=True),
        name="web",
    )
    logger.info("Mini App подключён: %s", _WEB_DIR)
else:
    logger.error(
        "Папка Mini App не найдена: %s — /app будет отдавать 404", _WEB_DIR
    )


@app.get("/health")
async def health_check():
    """Health check — мгновенный ответ, без БД и Telegram."""
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "service": "Tattoo Bot API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# ─── Webhook endpoint ───────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """Обработка webhook-уведомлений от Telegram.

    Правило: отвечаем 200 на ВСЁ, кроме неверного секрета (403) и битого
    JSON (400). Любой другой исход — 200, потому что на не-2xx Telegram
    повторяет тот же update бесконечно (это и давало «приветствие каждые
    2 минуты»). Причина ошибки уходит в лог, а не в Telegram.
    """
    # Проверка secret_token (если он настроен)
    secret_from_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.webhook_secret and secret_from_header != settings.webhook_secret:
        logger.warning("Несоответствие secret token")
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"status": "error", "detail": "Unauthorized"},
        )

    # Разбираем тело
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("Ошибка парсинга JSON: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "error", "detail": "Invalid JSON"},
        )

    # Dispatcher отсутствует — это наша проблема, не Telegram.
    # Всё равно 200, иначе повторы никогда не прекратятся.
    if dp is None or bot is None:
        logger.error(
            "Dispatcher/бот не инициализированы — update %s отброшен",
            payload.get("update_id", "?"),
        )
        return {"status": "ok", "detail": "dispatcher not ready"}

    # Обрабатываем
    from aiogram.types import Update

    try:
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as exc:
        logger.error(
            "Ошибка обработки update %s: %s: %s",
            payload.get("update_id", "?"),
            type(exc).__name__,
            exc,
            exc_info=True,
        )

    return {"status": "ok"}
