"""CRUD + transitions для заявок.

Все эндпоинты защищены Telegram-авторизацией. Клиент не передаёт user_id:
личность берётся из подписанного initData, иначе любой мог бы создать
заявку от чужого имени.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    admin_only,
    get_current_user,
    load_request_for_user,
    owner_of_request,
)
from app.database import get_db
from app.dependencies import (
    BadRequestError,
    ConflictError,
    InvalidTransitionError,
    RequestNotFoundError,
)
from app.models import (
    Appointment,
    MasterSlot,
    TattooRequest,
    TgUser,
)
from app.schemas import (
    AdminDashboard,
    TattooRequestCreate,
    TattooRequestDraftUpdate,
    TattooRequestOut,
)
from app.utils.state_machine import get_transition_description, is_valid_transition

logger = logging.getLogger(__name__)

router = APIRouter(tags=["requests"])

# Связи, нужные для сериализации TattooRequestOut.
# Вложенный appointment.slot загружается тоже: иначе property slot_date
# попытается лениво дочитать данные и упадёт с MissingGreenlet.
# user нужен для client_name / client_username (мастер должен видеть, кто пишет).
_FULL_OPTIONS = (
    selectinload(TattooRequest.references),
    selectinload(TattooRequest.brief_questions),
    selectinload(TattooRequest.appointment).selectinload(Appointment.slot),
    selectinload(TattooRequest.user),
)


# ─── helpers ────────────────────────────────────────────────────────────────


async def _ensure_user(
    session: AsyncSession, user_id: int, user_data: dict[str, Any] | None
) -> None:
    """Гарантирует, что пользователь есть в tg_user.

    Mini App может открыться раньше, чем человек нажмёт /start в боте.
    Без этой записи заявка упадёт на внешнем ключе.
    """
    existing = await session.execute(select(TgUser).where(TgUser.tg_id == user_id))
    if existing.scalar_one_or_none():
        return

    data = user_data or {}
    session.add(
        TgUser(
            tg_id=user_id,
            first_name=(data.get("first_name") or "Гость")[:100],
            last_name=(data.get("last_name") or None),
            username=(data.get("username") or None),
        )
    )
    await session.flush()


def _validate_transition(current: str, target: str) -> None:
    if not is_valid_transition(current, target):
        raise InvalidTransitionError(
            f"Недопустимый переход: {current} → {target}. "
            f"Допустимые: {get_transition_description(current, target)}"
        )


async def _load_locked(session: AsyncSession, request_id: int) -> TattooRequest:
    """Заявка со связями и блокировкой строки (защита от гонок).

    populate_existing обязателен: после commit объект уже лежит в identity map
    с ранее загруженными связями, и обычный запрос вернул бы устаревшие
    значения (например, appointment=None сразу после назначения даты).
    """
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
        .options(*_FULL_OPTIONS)
        .execution_options(populate_existing=True)
    )
    req = (await session.execute(stmt)).scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()
    return req


# ─── GET /api/v1/me ─────────────────────────────────────────────────────────


@router.get("/me")
async def me(
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    """Кто я: id, имя и признак мастера. Нужно для кабинета в Mini App."""
    await _ensure_user(
        session, current_user["user_id"], current_user.get("user")
    )
    await session.commit()

    data = current_user.get("user") or {}
    return {
        "user_id": current_user["user_id"],
        "is_admin": current_user["is_admin"],
        "first_name": data.get("first_name") or "Клиент",
        "last_name": data.get("last_name"),
        "username": data.get("username"),
    }


# ─── POST /api/v1/requests — создание заявки ────────────────────────────────


@router.post(
    "/requests", response_model=TattooRequestOut, status_code=status.HTTP_201_CREATED
)
async def create_request(
    data: TattooRequestCreate,
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Создаёт заявку сразу в статусе 'new' (то есть отправленную).

    user_id и created_by намеренно НЕ берутся из тела запроса — только
    из проверенного initData.
    """
    user_id: int = current_user["user_id"]
    await _ensure_user(session, user_id, current_user.get("user"))

    req = TattooRequest(
        user_id=user_id,
        created_by=user_id,
        description=data.description.strip(),
        location=data.location.strip(),
        size=data.size.strip(),
        color_mode=data.color_mode,
        is_urgent=bool(data.is_urgent),
        urgent_surcharge=data.urgent_surcharge,
        brief_answers=data.brief_answers or None,
        status="new",
    )
    session.add(req)
    await session.commit()

    # Перечитываем со связями, иначе сериализация упадёт
    created = await _load_locked(session, req.id)
    await _notify_master_new_request(req)
    return created


async def _notify_master_new_request(req: TattooRequest) -> None:
    """Сообщает мастеру о новой заявке. Ошибка не ломает создание."""
    try:
        from app.bot.services.notification_service import NotificationService
        from app.config import get_settings

        settings = get_settings()
        if settings.master_tg_id <= 0:
            return

        # Импортируем lazily: в API-режиме бот может быть не инициализирован.
        from app.main import bot as running_bot

        if running_bot is None:
            logger.warning(
                "Бот не инициализирован — уведомление о заявке #%s не отправлено",
                req.id,
            )
            return

        service = NotificationService(running_bot)
        text = (
            "🖋 Новая заявка #%s\n\n"
            "💬 %s\n"
            "📍 %s\n"
            "📏 %s\n"
            "🎨 %s%s"
        ) % (
            req.id,
            req.description[:300],
            req.location,
            req.size,
            "цветная" if req.color_mode == "color" else "чёрно-белая",
            "\n⚡ срочная" if req.is_urgent else "",
        )
        await service.send_message(settings.master_tg_id, text)
    except Exception:
        logger.exception("Не удалось уведомить мастера о заявке #%s", req.id)


# ─── GET /api/v1/requests ───────────────────────────────────────────────────


@router.get("/requests", response_model=list[TattooRequestOut])
async def list_requests(
    status_filter: str | None = Query(None, alias="status"),
    archived: bool | None = None,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Список заявок. Мастер видит все, клиент — только свои.

    Архивные заявки по умолчанию скрыты: мастер убрал их в корзину,
    значит клиент не должен видеть их снова в «Моих заявках».
    """
    stmt = (
        select(TattooRequest)
        .options(*_FULL_OPTIONS)
        .order_by(TattooRequest.created_at.desc())
    )

    if status_filter:
        stmt = stmt.where(TattooRequest.status == status_filter)

    # Явный запрос архива — только для мастера (клиенту архив не нужен).
    if archived is True and current_user.get("is_admin"):
        stmt = stmt.where(TattooRequest.is_archived == True)  # noqa: E712
    else:
        stmt = stmt.where(TattooRequest.is_archived == False)  # noqa: E712

    if not current_user.get("is_admin"):
        stmt = stmt.where(TattooRequest.user_id == current_user["user_id"])

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


# ─── GET /api/v1/requests/{id} ──────────────────────────────────────────────


@router.get("/requests/{request_id}", response_model=TattooRequestOut)
async def get_request(
    request_id: int,
    req: TattooRequest = Depends(owner_of_request),
):
    """Детальная информация по заявке."""
    return req


# ─── PATCH /api/v1/requests/{id} — обновление черновика ─────────────────────


@router.patch("/requests/{request_id}", response_model=TattooRequestOut)
async def update_draft(
    request_id: int,
    data: TattooRequestDraftUpdate,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
):
    """Обновление полей черновика (только для status='draft')."""
    if req.status != "draft":
        raise InvalidTransitionError("Можно обновлять только черновик (status=draft)")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(req, field, value)

    await session.commit()
    return await _load_locked(session, request_id)


# ─── POST /api/v1/requests/{id}/finalize ────────────────────────────────────


@router.post("/requests/{request_id}/finalize", response_model=TattooRequestOut)
async def finalize_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
):
    """Финализация черновика → 'new'."""
    if req.status != "draft":
        raise InvalidTransitionError("Можно финализировать только черновик (status=draft)")

    req.status = "new"
    await session.commit()
    return await _load_locked(session, request_id)


# ─── Переходы статусов (только мастер) ──────────────────────────────────────


@router.post("/requests/{request_id}/accept", response_model=TattooRequestOut)
async def accept_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Мастер принимает заявку (new → accepted)."""
    req = await _load_locked(session, request_id)
    _validate_transition(req.status, "accepted")
    req.status = "accepted"
    await session.commit()
    return await _load_locked(session, request_id)


class RejectPayload(BaseModel):
    reason: str | None = None


@router.post("/requests/{request_id}/reject", response_model=TattooRequestOut)
async def reject_request(
    request_id: int,
    data: RejectPayload | None = None,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Мастер отклоняет заявку."""
    req = await _load_locked(session, request_id)
    _validate_transition(req.status, "rejected")
    req.status = "rejected"
    if data and data.reason:
        req.rejection_reason = data.reason
    await session.commit()
    return await _load_locked(session, request_id)


@router.post("/requests/{request_id}/proceed", response_model=TattooRequestOut)
async def proceed_to_sketch(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Мастер берётся за эскиз (accepted → in_progress)."""
    req = await _load_locked(session, request_id)
    _validate_transition(req.status, "in_progress")
    req.status = "in_progress"
    await session.commit()
    return await _load_locked(session, request_id)


class SchedulePayload(BaseModel):
    slot_date: str  # ISO date: "YYYY-MM-DD"


@router.post("/requests/{request_id}/schedule", response_model=TattooRequestOut)
async def schedule_request(
    request_id: int,
    data: SchedulePayload,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Назначить дату сеанса (in_progress → scheduled)."""
    try:
        target_date = date_type.fromisoformat(data.slot_date)
    except ValueError:
        raise BadRequestError("Дата должна быть в формате ГГГГ-ММ-ДД")

    req = await _load_locked(session, request_id)
    _validate_transition(req.status, "scheduled")

    slot = (
        await session.execute(
            select(MasterSlot).where(MasterSlot.slot_date == target_date)
        )
    ).scalar_one_or_none()

    if not slot:
        slot = MasterSlot(slot_date=target_date, is_blocked=True)
        session.add(slot)
        await session.flush()

    busy = await session.execute(
        select(Appointment).where(
            Appointment.slot_id == slot.id,
            Appointment.status.in_(["confirmed", "done"]),
        )
    )
    if busy.scalar_one_or_none():
        raise ConflictError(f"На дату {target_date} уже есть активная запись")

    session.add(Appointment(request_id=req.id, slot_id=slot.id, status="confirmed"))
    req.status = "scheduled"
    await session.commit()
    return await _load_locked(session, request_id)


@router.post("/requests/{request_id}/complete", response_model=TattooRequestOut)
async def complete_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Завершить сеанс (scheduled → completed)."""
    req = await _load_locked(session, request_id)
    _validate_transition(req.status, "completed")

    if not req.appointment:
        raise BadRequestError("У заявки нет активной записи")

    req.appointment.status = "done"
    req.status = "completed"
    await session.commit()
    return await _load_locked(session, request_id)


@router.post("/requests/{request_id}/cancel", response_model=TattooRequestOut)
async def cancel_appointment(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Отменить запись, вернуть заявку в очередь."""
    req = await _load_locked(session, request_id)

    if not req.appointment:
        raise BadRequestError("У заявки нет активной записи")

    req.appointment.status = "cancelled"
    if req.status == "scheduled":
        req.status = "new"

    await session.commit()
    return await _load_locked(session, request_id)


@router.post("/requests/{request_id}/reactivate", response_model=TattooRequestOut)
async def reactivate_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Возобновить заявку из rejected (rejected → new)."""
    req = await _load_locked(session, request_id)

    if req.status != "rejected":
        raise InvalidTransitionError(
            f"Заявка не в статусе rejected (текущий: {req.status})"
        )

    req.status = "new"
    req.rejection_reason = None
    req.rejected_at = None
    req.queue_order = None
    req.queue_rank = None
    await session.commit()
    return await _load_locked(session, request_id)


# ─── Корзина ────────────────────────────────────────────────────────────────


@router.get("/trash", response_model=list[TattooRequestOut])
async def get_trash(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Завершённые заявки (корзина)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.status.in_(["completed", "rejected", "cancelled"]))
        .options(*_FULL_OPTIONS)
        .order_by(TattooRequest.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


@router.delete("/trash/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_from_trash(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Скрыть заявку в архиве."""
    req = await session.get(TattooRequest, request_id)
    if not req:
        raise RequestNotFoundError()

    req.is_archived = True
    await session.commit()