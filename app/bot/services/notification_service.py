"""Сервис отправки уведомлений через Telegram."""

from __future__ import annotations

import logging

from aiogram import Bot

logger = logging.getLogger(__name__)


class NotificationService:
    """Отправка сообщений через Telegram Bot API + запись в лог.

    Логирование идёт в отдельной сессии и никогда не роняет отправку:
    уведомление — вспомогательная вещь, из-за него нельзя терять заявку.
    """

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
        """Отправляет сообщение и логирует результат."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text)
            await self._log(request_id, notification_type, chat_id, "sent", None)
            return True
        except Exception as exc:
            logger.warning(
                "Не удалось отправить уведомление chat_id=%s: %s", chat_id, exc
            )
            await self._log(request_id, notification_type, chat_id, "failed", str(exc))
            return False

    async def send_inline_keyboard(
        self,
        chat_id: int,
        text: str,
        keyboard,
        *,
        request_id: int | None = None,
        notification_type: str = "info",
    ) -> bool:
        """Отправляет сообщение с inline-клавиатурой."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard)
            await self._log(request_id, notification_type, chat_id, "sent", None)
            return True
        except Exception as exc:
            logger.warning(
                "Не удалось отправить сообщение chat_id=%s: %s", chat_id, exc
            )
            await self._log(request_id, notification_type, chat_id, "failed", str(exc))
            return False

    async def _log(
        self,
        request_id: int | None,
        notification_type: str,
        chat_id: int,
        status: str,
        error_msg: str | None,
    ) -> None:
        """Пишет запись в notification_log.

        request_id в таблице обязательный, поэтому логируем только то,
        что привязано к заявке. Всё остальное — в обычный лог приложения.
        """
        if request_id is None:
            return

        try:
            from app.database import async_session_factory
            from app.models import NotificationLog

            async with async_session_factory() as session:
                session.add(
                    NotificationLog(
                        request_id=request_id,
                        type=notification_type[:50],
                        tg_chat_id=chat_id,
                        status=status,
                        error_msg=(error_msg or None) and error_msg[:500],
                    )
                )
                await session.commit()
        except Exception:
            logger.debug("Не удалось записать notification_log", exc_info=True)

    # ─── Шаблоны ─────────────────────────────────────────────────────────

    @staticmethod
    def request_created(request_id: int) -> str:
        return f"✅ Ваша заявка #{request_id} отправлена! Мастер скоро посмотрит."

    @staticmethod
    def request_accepted(request_id: int) -> str:
        return f"✅ Заявка #{request_id} принята! Мастер уже работает над ней."

    @staticmethod
    def request_rejected(request_id: int, reason: str | None) -> str:
        if reason:
            return f"❌ Заявка #{request_id} отклонена.\n\nПричина: {reason}"
        return f"❌ Заявка #{request_id} отклонена. Напиши мастеру, чтобы обсудить детали."

    @staticmethod
    def request_in_progress(request_id: int) -> str:
        return f"🖌 Заявка #{request_id} — мастер берётся за эскиз!"

    @staticmethod
    def appointment_scheduled(request_id: int, slot_date: str) -> str:
        return (
            f"📅 Заявка #{request_id}: дата сеанса {slot_date}.\n\n"
            "Напиши мастеру, чтобы подтвердить время."
        )

    @staticmethod
    def appointment_completed(request_id: int) -> str:
        return f"✨ Заявка #{request_id} завершена!\n\nСпасибо, что доверили свою тату! 💛"

    @staticmethod
    def appointment_cancelled(request_id: int) -> str:
        return f"🚫 Запись по заявке #{request_id} отменена."

    @staticmethod
    def welcome_message() -> str:
        return (
            "✨ Привет! Я Ариадна — тату-мастер.\n\n"
            "Здесь можно оставить заявку на эскиз и следить за её статусом.\n\n"
            "Нажми кнопку ниже — всё остальное в приложении ✍️"
        )