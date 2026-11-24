"""Сервис управления заявками: CRUD и state transitions."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import (
    ConflictError,
    InvalidTransitionError,
    RequestNotFoundError,
)
from app.models import (
    Appointment,
    BriefQuestion,
    MasterSlot,
    NotificationLog,
    RequestReference,
    TattooRequest,
)
from app.schemas import (
    TattooRequestCreate,
    TattooRequestDraftUpdate,
)
from app.utils.state_machine import is_valid_transition


async def create_draft(
    session: AsyncSession,
    user_id: int,
    description: str,
    **kwargs,
) -> TattooRequest:
    """Создаёт черновик заявки (P0-1: статус 'draft' с самого начала)."""
    request = TattooRequest(
        user_id=user_id,
        created_by=user_id,
        status="draft",
        description=description,
        **{k: v for k, v in kwargs.items() if v is not None},
    )
    session.add(request)
    await session.flush()
    return request


async def update_draft(
    session: AsyncSession,
    request_id: int,
    user_id: int,
    data: TattooRequestDraftUpdate,
) -> TattooRequest:
    """Обновляет поля черновика. P0-1: обновление всех полей в БД."""
    stmt = (
        select(TattooRequest)
        .where(
            TattooRequest.id == request_id,
            TattooRequest.user_id == user_id,
            TattooRequest.status == "draft",
        )
        .options(
            selectinload(TattooRequest.references),
            selectinload(TattooRequest.brief_questions),
        )
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(req, field, value)

    await session.flush()
    return req


async def finalize_request(
    session: AsyncSession,
    request_id: int,
    user_id: int,
    references: list[RequestReference] | None = None,
    brief_questions: list[BriefQuestion] | None = None,
) -> TattooRequest:
    """Финализация черновика → статус 'new'. P0-1, P0-4."""
    stmt = (
        select(TattooRequest)
        .where(
            TattooRequest.id == request_id,
            TattooRequest.user_id == user_id,
            TattooRequest.status == "draft",
        )
        .options(
            selectinload(TattooRequest.references),
            selectinload(TattooRequest.brief_questions),
        )
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    # P0-1: Меняем status на 'new'
    req.status = "new"
    req.updated_at = datetime.utcnow()

    # Сохраняем референсы
    if references:
        for ref in references:
            ref.request_id = request_id
            session.add(ref)

    # Сохраняем бриф-вопросы
    if brief_questions:
        for bq in brief_questions:
            bq.request_id = request_id
            session.add(bq)

    await session.flush()
    return req


async def get_request_by_id(
    session: AsyncSession,
    request_id: int,
) -> TattooRequest:
    """Получает заявку по ID с загруженными связями."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .options(
            selectinload(TattooRequest.references),
            selectinload(TattooRequest.brief_questions),
            selectinload(TattooRequest.appointment),
        )
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()
    return req


async def list_requests(
    session: AsyncSession,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
    user_id: int | None = None,
    archived: bool | None = None,
) -> Sequence[TattooRequest]:
    """Список заявок с фильтрацией."""
    stmt = select(TattooRequest).order_by(TattooRequest.created_at.desc())

    if status:
        stmt = stmt.where(TattooRequest.status == status)
    if user_id:
        stmt = stmt.where(TattooRequest.user_id == user_id)
    if archived is not None:
        stmt = stmt.where(TattooRequest.is_archived == archived)

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


async def archive_old_requests(session: AsyncSession) -> int:
    """Помечает завершённые заявки старше 30 дней как архивные."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=30)

    stmt = (
        update(TattooRequest)
        .where(
            TattooRequest.status.in_(["completed", "rejected", "cancelled"]),
            TattooRequest.updated_at < cutoff,
            TattooRequest.is_archived == False,
        )
        .values(is_archived=True)
    )
    result = await session.execute(stmt)
    await session.flush()
    return result.rowcount


# ─── Status Transitions (P0-4: в транзакциях) ────────────────────────────────


async def transition_status(
    session: AsyncSession,
    request_id: int,
    new_status: str,
    *,
    extra_fields: dict | None = None,
) -> TattooRequest:
    """
    Атомарный переход статуса заявки. P0-4: обёрнут в транзакцию.
    Валидирует переход через state_machine.
    """
    from app.utils.state_machine import is_valid_transition

    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()  # Блокировка строки
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    if not is_valid_transition(req.status, new_status):
        raise InvalidTransitionError(
            f"Недопустимый переход: {req.status} → {new_status}"
        )

    old_status = req.status
    req.status = new_status
    req.updated_at = datetime.utcnow()

    # Устанавливаем timestamp в зависимости от статуса
    now = datetime.utcnow()
    if new_status == "accepted":
        req.accepted_at = now
    elif new_status == "rejected":
        req.rejected_at = now
    elif new_status == "scheduled":
        req.assigned_at = now
    elif new_status == "completed":
        req.completed_at = now

    # Дополнительные поля
    if extra_fields:
        for field, value in extra_fields.items():
            setattr(req, field, value)

    await session.flush()
    return req


async def reset_rejection(
    session: AsyncSession,
    request_id: int,
) -> TattooRequest:
    """Возобновление заявки из rejected → new. Очищает поля rejection."""
    stmt = (
        select(TattooRequest)
        .where(
            TattooRequest.id == request_id,
            TattooRequest.status == "rejected",
        )
        .with_for_update()
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    req.status = "new"
    req.rejection_reason = None
    req.rejected_at = None
    req.queue_order = None
    req.queue_rank = None
    req.updated_at = datetime.utcnow()

    await session.flush()
    return req


async def cancel_appointment(
    session: AsyncSession,
    request_id: int,
) -> TattooRequest:
    """Отмена записи: appointment → cancelled, статус заявки → new."""
    from app.utils.state_machine import is_valid_transition

    # Получаем заявку
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .options(selectinload(TattooRequest.appointment))
        .with_for_update()
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    if not req.appointment:
        raise InvalidTransitionError("У заявки нет активной записи")

    # Отменяем appointment
    req.appointment.status = "cancelled"

    # Возвращаем заявку в new
    if is_valid_transition(req.status, "new"):
        req.status = "new"
        req.updated_at = datetime.utcnow()

    await session.flush()
    return req


async def complete_session(
    session: AsyncSession,
    request_id: int,
    slot_date: datetime | None = None,
) -> TattooRequest:
    """Завершение сеанса: appointment → done, статус → completed."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .options(selectinload(TattooRequest.appointment))
        .with_for_update()
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    if not req.appointment:
        raise InvalidTransitionError("У заявки нет активной записи")

    # Завершаем appointment
    req.appointment.status = "done"

    # Создаём заблокированный слот если его нет
    if slot_date:
        slot_stmt = select(MasterSlot).where(MasterSlot.slot_date == slot_date)
        slot_result = await session.execute(slot_stmt)
        slot = slot_result.scalar_one_or_none()
        if not slot:
            slot = MasterSlot(slot_date=slot_date, is_blocked=True)
            session.add(slot)
        else:
            slot.is_blocked = True
    else:
        # Используем слот из appointment
        slot = req.appointment.slot
        slot.is_blocked = True

    # Обновляем статус заявки
    req.status = "completed"
    req.completed_at = datetime.utcnow()
    req.updated_at = datetime.utcnow()

    await session.flush()
    return req
