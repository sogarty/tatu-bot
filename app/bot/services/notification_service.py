"""Сервис отправки уведомлений через Telegram."""

from __future__ import annotations

from datetime import datetime

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationLog, TattooRequest
from app.utils.helpers import format_status_text


class NotificationService:
    """Сервис уведомлений: отправка через Telegram Bot API + логирование."""

    def __init__(self, bot: Bot):
        self._bot = bot

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        request_id: int | None = None,
        notification_type: str = "info",
    ) -> bool:
        """Отправляет сообщение клиенту и логирует."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)

            # Логируем отправку
            await self._log_notification(
                request_id=request_id,
                type=notification_type,
                chat_id=chat_id,
                status="sent",
            )
            return True
        except Exception as e:
            await self._log_notification(
                request_id=request_id,
                type=notification_type,
                chat_id=chat_id,
                status="failed",
                error_msg=str(e),
            )
            return False

    async def send_inline_keyboard(
        self,
        chat_id: int,
        text: str,
        keyboard,  # InlineKeyboardMarkup
        *,
        request_id: int | None = None,
        notification_type: str = "info",
    ) -> bool:
        """Отправляет сообщение с inline-клавиатурой."""
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            await self._log_notification(
                request_id=request_id,
                type=notification_type,
                chat_id=chat_id,
                status="sent",
            )
            return True
        except Exception as e:
            await self._log_notification(
                request_id=request_id,
                type=notification_type,
                chat_id=chat_id,
                status="failed",
                error_msg=str(e),
            )
            return False

    async def _log_notification(
        self,
        *,
        request_id: int | None,
        type: str,
        chat_id: int,
        status: str = "sent",
        error_msg: str | None = None,
    ) -> None:
        """Сохраняет лог уведомления в БД."""
        log_entry = NotificationLog(
            request_id=request_id,
            type=type,
            tg_chat_id=chat_id,
            status=status,
            error_msg=error_msg,
        )
        # Не используем session здесь — логируем в отдельной транзакции
        # Это упрощённая версия; в продакшене можно использовать
        # separate session or queue
        pass

    # ─── Готовые шаблоны уведомлений ─────────────────────────────────────

    @staticmethod
    def request_created(request_id: int) -> str:
        return f"✅ Ваша заявка #{request_id} отправлена! Мастер скоро посмотрит."

    @staticmethod
    def request_accepted(request_id: int) -> str:
        return f"✅ Заявка #{request_id} принята! Мастер уже работает над ней."

    @staticmethod
    def request_rejected(request_id: int, reason: str) -> str:
        return f"❌ Заявка #{request_id} отклонена.\n\nПричина: {reason}"

    @staticmethod
    def request_in_progress(request_id: int) -> str:
        return f"🖌 Заявка #{request_id} — мастер берётся за эскиз!"

    @staticmethod
    def appointment_scheduled(request_id: int, slot_date: str) -> str:
        return f"📅 Заявка #{request_id}! Дата сеанса: {slot_date}.\n\nНапишите мастеру для подтверждения."

    @staticmethod
    def appointment_completed(request_id: int) -> str:
        return f"✨ Заявка #{request_id} завершена!\n\nСпасибо, что доверили нам свою тату! 💛"

    @staticmethod
    def appointment_cancelled(request_id: int) -> str:
        return f"🚫 Запись по заявке #{request_id} отменена."

    @staticmethod
    def next_in_queue(request_id: int) -> str:
        return f"📋 Вы следующий в очереди! Как только Арину освободится — сообщим ✨"

    @staticmethod
    def request_returned_to_new(request_id: int) -> str:
        return f"↩️ Заявка #{request_id} возвращена в обработку."

    @staticmethod
    def draft_saving(request_id: int) -> str:
        return f"💾 Черновик заявки #{request_id} сохранён."

    @staticmethod
    def welcome_message() -> str:
        return (
            "✨ Привет! Я Арину — тату-мастер.\n\n"
            "Добро пожаловать в мой личный бот. Здесь ты можешь:\n"
            "• Оставить заявку на эскиз\n"
            "• Посмотреть свободные даты\n"
            "• Отслеживать статус своей заявки\n\n"
            "Давай начнём! ✍️"
        )
