"""Обработчики клиентских команд: /start, /cancel, меню."""

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Message,
    ReplyKeyboardRemove,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import get_main_keyboard
from app.bot.services.notification_service import NotificationService
from app.config import get_settings
from app.models import TgUser
from app.utils.helpers import format_user_name

router = Router(name="client")


def register_handlers(dp):
    dp.include_router(router)


@router.message(Command("start"))
async def cmd_start(
    message: Message,
    session: AsyncSession,
):
    """Регистрация пользователя и показ главного меню."""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name
    username = message.from_user.username

    # Проверяем, существует ли пользователь
    result = await session.execute(
        select(TgUser).where(TgUser.tg_id == user_id)
    )
    tg_user = result.scalar_one_or_none()

    if tg_user:
        # Обновляем данные
        tg_user.first_name = first_name
        tg_user.last_name = last_name
        tg_user.username = username
        tg_user.updated_at = datetime.utcnow()
    else:
        # Создаём нового пользователя
        tg_user = TgUser(
            tg_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        session.add(tg_user)

    # Получаем приветственное сообщение
    from app.models import BotSettings
    result = await session.execute(
        select(BotSettings).where(BotSettings.id == 1)
    )
    settings = result.scalar_one_or_none()
    welcome_msg = (
        settings.welcome_message
        if settings and settings.welcome_message
        else NotificationService.welcome_message()
    )

    await message.answer(
        welcome_msg,
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("cancel"))
@router.message(F.text.lower() == "отмена")
async def cmd_cancel(
    message: Message,
    state,
):
    """Отмена текущего FSM-состояния. P0-7: мгновенная отмена."""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer(
            "🗑 Действие отменено.",
            reply_markup=get_main_keyboard(),
        )
    else:
        await message.answer(
            "❌ Нет активного действия для отмены.",
            reply_markup=get_main_keyboard(),
        )


@router.message(F.text == "📋 Мои заявки")
async def cmd_my_requests(
    message: Message,
    session: AsyncSession,
):
    """Показывает активные заявки пользователя."""
    user_id = message.from_user.id

    from app.models import TattooRequest
    from app.utils.helpers import format_status_text, truncate_text

    result = await session.execute(
        select(TattooRequest)
        .where(
            TattooRequest.user_id == user_id,
            TattooRequest.status.in_(
                ["draft", "new", "accepted", "in_progress", "scheduled"]
            ),
            TattooRequest.is_archived == False,
        )
        .order_by(TattooRequest.created_at.desc())
        .limit(5)
    )
    requests = list(result.scalars().all())

    if not requests:
        await message.answer(
            "📋 У тебя пока нет активных заявок.\n\n"
            "Но ты всегда можешь создать новую! ✨",
            reply_markup=get_main_keyboard(),
        )
        return

    lines = ["📋 <b>Мои заявки:</b>\n"]
    for req in requests:
        status_text = format_status_text(req.status)
        preview = truncate_text(req.description, 60)
        lines.append(
            f"#{req.id} — {status_text}\n"
            f"  {preview}"
        )
        lines.append("")

    await message.answer(
        "\n".join(lines).strip(),
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == "💬 Написать мастеру")
async def cmd_write_master(
    message: Message,
):
    """Открывает профиль TG мастера."""
    settings = get_settings()
    if settings.master_tg_id:
        master_url = f"https://t.me/{settings.master_tg_id}"
        await message.answer(
            f"💬 Напиши мастеру напрямую: "
            f"<a href='{master_url}'>Открыть в Telegram</a>",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "💬 Контакты мастера скоро появятся!",
            reply_markup=get_main_keyboard(),
        )
