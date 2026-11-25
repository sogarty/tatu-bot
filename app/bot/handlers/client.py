"""Обработчики клиентских команд: /start и подсказка на прочие сообщения.

Бот намеренно максимально тонкий: вся работа с заявками живёт в Mini App.
Здесь только приветствие и кнопка «Открыть приложение».

Роутер собирается функцией build_router(), а не один раз при импорте:
aiogram запрещает подключать один и тот же Router к двум Dispatcher'ам,
и модульный синглтон ломал повторную инициализацию в том же процессе.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import TgUser

logger = logging.getLogger(__name__)


def _app_url() -> str:
    """Адрес Mini App.

    Приоритет — WEBAPP_URL из настроек. Если он не задан, собираем адрес
    от WEBHOOK_BASE_URL: так кнопка не исчезнет из-за забытой переменной.
    """
    settings = get_settings()

    url = (settings.webapp_url or "").strip()
    if url:
        return url.rstrip("/") + "/"

    base = (settings.webhook_base_url or "").strip()
    if base:
        return base.rstrip("/") + "/app/"

    return ""


def _app_keyboard() -> InlineKeyboardMarkup | None:
    """Кнопка открытия Mini App. None — если адрес определить не удалось."""
    url = _app_url()
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=url))]
        ]
    )


WELCOME_TEXT = (
    "✨ Привет!\n\n"
    "Здесь можно оставить заявку на тату:\n"
    "• рассказать идею\n"
    "• посмотреть свободные даты\n"
    "• следить за статусом заявки\n\n"
    "Нажми кнопку ниже — всё остальное в приложении ✍️"
)

NO_APP_TEXT = (
    "✨ Привет!\n\n"
    "Приложение скоро будет доступно — напиши мастеру в личные сообщения, "
    "чтобы оставить заявку."
)


async def cmd_start(message: Message, session: AsyncSession) -> None:
    """Регистрирует пользователя в БД и показывает кнопку Mini App."""
    if message.from_user is None:
        return

    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name
    username = message.from_user.username

    # ── 1. Сначала данные в БД ────────────────────────────────────────────
    # Раньше ответ отправлялся до коммита: сообщение уходило, а запись
    # откатывалась. Теперь наоборот — сначала сохраняем, потом отвечаем.
    try:
        result = await session.execute(select(TgUser).where(TgUser.tg_id == user_id))
        tg_user = result.scalar_one_or_none()

        if tg_user is None:
            session.add(
                TgUser(
                    tg_id=user_id,
                    first_name=first_name or "Гость",
                    last_name=last_name,
                    username=username,
                )
            )
        else:
            tg_user.first_name = first_name or tg_user.first_name
            tg_user.last_name = last_name
            tg_user.username = username
            tg_user.updated_at = datetime.now(timezone.utc)

        await session.commit()
    except Exception:
        # База недоступна — не молчим, но и не роняем обработчик.
        await session.rollback()
        logger.exception("Не удалось сохранить пользователя tg_id=%s", user_id)

    # ── 2. Потом ответ ────────────────────────────────────────────────────
    keyboard = _app_keyboard()
    await message.answer(
        WELCOME_TEXT if keyboard else NO_APP_TEXT,
        reply_markup=keyboard,
    )


async def handle_any_text(message: Message) -> None:
    """Любое прочее сообщение — короткая подсказка, без спама приветствием."""
    keyboard = _app_keyboard()
    await message.answer(
        "Открой приложение — там заявка, даты и статус 👇" if keyboard
        else "Приложение скоро будет доступно. Напиши мастеру в личку.",
        reply_markup=keyboard,
    )


def build_router() -> Router:
    """Создаёт новый Router с клиентскими обработчиками."""
    router = Router(name="client")
    router.message.register(cmd_start, Command("start"))
    # Ловушка на текст. Регистрируется последней и не перехватывает команды:
    # сообщения, начинающиеся с «/», ей не подходят.
    router.message.register(
        handle_any_text, F.text & ~F.text.startswith("/")
    )
    return router


def register_handlers(dp) -> None:
    """Совместимость со старым вызовом."""
    dp.include_router(build_router())