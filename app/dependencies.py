from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MasterWhitelist, TgUser


class AdminUser:
    """Упрощённый объект авторизованного администратора."""

    def __init__(self, user: TgUser | None, is_admin: bool):
        self.user = user
        self.is_admin = is_admin
        self.tg_id: int = user.tg_id if user else 0


async def get_current_admin_user(
    session: AsyncSession = Depends(get_db),
) -> AdminUser:
    """
    Проверка, что пользователь из Admin API (через Bearer token).
    В реальной реализации — проверка API ключа из Authorization заголовка.
    """
    from app.config import get_settings
    settings = get_settings()

    return AdminUser(user=None, is_admin=bool(settings.master_tg_id))


class MasterWhitelistChecker:
    """Проверяет, есть ли tg_id в whitelist мастеров."""

    def __init__(self, allowed_ids: set[int]):
        self._allowed_ids = allowed_ids

    def is_master(self, tg_id: int) -> bool:
        return tg_id in self._allowed_ids

    async def refresh(self, session: AsyncSession) -> None:
        result = await session.execute(select(MasterWhitelist.tg_id))
        self._allowed_ids = {row[0] for row in result.all()}


async def get_master_whitelist_checker(
    session: AsyncSession = Depends(get_db),
) -> MasterWhitelistChecker:
    """Зависимость, загружающая whitelist при каждом запросе."""
    from app.config import get_settings
    settings = get_settings()

    result = await session.execute(select(MasterWhitelist.tg_id))
    allowed_ids = {row[0] for row in result.all()}
    if settings.master_tg_id:
        allowed_ids.add(settings.master_tg_id)
    return MasterWhitelistChecker(allowed_ids)


# ─── HTTP Exceptions ─────────────────────────────────────────────────────────


class UnauthorizedError(HTTPException):
    def __init__(self, detail: str = "Unauthorized") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
        )


class UserNotFoundError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )


class RequestNotFoundError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Заявка не найдена",
        )


class InvalidTransitionError(HTTPException):
    def __init__(self, message: str = "Недопустимый переход статуса") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


class BadRequestError(HTTPException):
    def __init__(self, message: str = "Некорректный запрос") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


class ForbiddenError(HTTPException):
    def __init__(self, message: str = "Доступ запрещён") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=message,
        )


class ConflictError(HTTPException):
    def __init__(self, message: str = "Конфликт данных") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=message,
        )
