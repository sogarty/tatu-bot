"""CRUD + transitions для заявок."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import admin_only, owner_of_request, get_current_user
from app.database import get_db
from app.dependencies import (
    BadRequestError,
    ConflictError,
    InvalidTransitionError,
    RequestNotFoundError,
)
from app.models import (
    Appointment,
    BriefQuestion,
    MasterSlot,
    RequestReference,
    TattooRequest,
)
from app.schemas import (
    RequestsFilter,
    TattooRequestOut,
    TattooRequestDraftUpdate,
    AdminDashboard,
)
from app.utils.state_machine import is_valid_transition, get_transition_description

router = APIRouter(tags=["requests"])


# ─── GET /api/v1/requests ────────────────────────────────────────────────────


@router.get("/requests", response_model=list[TattooRequestOut])
async def list_requests(
    status_filter: str | None = Query(None, alias="status"),
    archived: bool | None = None,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Список заявок с фильтрацией и пагинацией.

    Admin видит все заявки. Обычный пользователь — только свои.
    """
    stmt = select(TattooRequest).order_by(TattooRequest.created_at.desc())

    if status_filter:
        stmt = stmt.where(TattooRequest.status == status_filter)
    if archived is not None:
        stmt = stmt.where(TattooRequest.is_archived == archived)

    # Обычный пользователь видит только свои заявки
    if not current_user.get("is_admin"):
        stmt = stmt.where(TattooRequest.user_id == current_user["user_id"])

    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    requests = list(result.scalars().all())
    return requests


# ─── GET /api/v1/requests/{id} ──────────────────────────────────────────────


@router.get("/requests/{request_id}", response_model=TattooRequestOut)
async def get_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
):
    """Детальная информация по заявке.

    Админ видит любые заявки. Обычный пользователь — только свои.
    """
    return req


# ─── PATCH /api/v1/requests/{id} — обновление черновика ─────────────────────


@router.patch("/requests/{request_id}", response_model=TattooRequestOut)
async def update_draft(
    request_id: int,
    data: TattooRequestDraftUpdate,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
):
    """Обновление полей черновика (только для статуса 'draft').

    Владелец заявки может обновлять только status='draft'.
    """
    if req.status != "draft":
        raise InvalidTransitionError("Можно обновлять только черновик (status=draft)")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(req, field, value)

    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/finalize ─────────────────────────────────────


@router.post("/requests/{request_id}/finalize", response_model=TattooRequestOut)
async def finalize_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
):
    """Финализация черновика → статус 'new'.

    Владелец может финализировать только свою заявку со статусом draft.
    """
    if req.status != "draft":
        raise InvalidTransitionError("Можно финализировать только черновик (status=draft)")

    req.status = "new"
    await session.commit()
    return req


# ─── Общие helpers для transition endpoints ──────────────────────────────────


def _validate_transition(current: str, target: str) -> None:
    if not is_valid_transition(current, target):
        raise InvalidTransitionError(
            f"Недопустимый переход: {current} → {target}. "
            f"Допустимые: {get_transition_description(current, target)}"
        )


# ─── POST /api/v1/requests/{id}/accept ──────────────────────────────────────


@router.post("/requests/{request_id}/accept", response_model=TattooRequestOut)
async def accept_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Мастер принимает заявку (new → accepted)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    _validate_transition(req.status, "accepted")

    req.status = "accepted"
    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/reject ──────────────────────────────────────


class RejectPayload(BaseModel):
    reason: str | None = None


@router.post("/requests/{request_id}/reject", response_model=TattooRequestOut)
async def reject_request(
    request_id: int,
    data: RejectPayload | None = None,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Мастер отклоняет заявку."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    _validate_transition(req.status, "rejected")

    req.status = "rejected"
    if data and data.reason:
        req.rejection_reason = data.reason
    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/proceed ─────────────────────────────────────


@router.post("/requests/{request_id}/proceed", response_model=TattooRequestOut)
async def proceed_to_sketch(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Мастер берётся за эскиз (accepted → in_progress)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    _validate_transition(req.status, "in_progress")

    req.status = "in_progress"
    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/schedule ────────────────────────────────────


class SchedulePayload(BaseModel):
    slot_date: str  # ISO date: "YYYY-MM-DD"


@router.post("/requests/{request_id}/schedule", response_model=TattooRequestOut)
async def schedule_request(
    request_id: int,
    data: SchedulePayload,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Назначить дату сеанса (in_progress → scheduled)."""
    from datetime import date as date_type
    from app.models import MasterSlot, Appointment

    target_date = date_type.fromisoformat(data.slot_date)

    # Получаем заявку
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    _validate_transition(req.status, "scheduled")

    # Ищем или создаём слот
    slot_stmt = select(MasterSlot).where(MasterSlot.slot_date == target_date)
    slot_result = await session.execute(slot_stmt)
    slot = slot_result.scalar_one_or_none()

    if not slot:
        slot = MasterSlot(slot_date=target_date, is_blocked=True)
        session.add(slot)
        await session.flush()

    # Проверяем, нет ли уже appointment для этого слота
    existing_appt = await session.execute(
        select(Appointment).where(
            Appointment.slot_id == slot.id,
            Appointment.status.in_(["confirmed", "done"]),
        )
    )
    if existing_appt.scalar_one_or_none():
        raise ConflictError(f"На дату {target_date} уже есть активная запись")

    # Создаём appointment
    appointment = Appointment(
        request_id=req.id,
        slot_id=slot.id,
        status="confirmed",
    )
    session.add(appointment)

    # Обновляем заявку
    req.status = "scheduled"
    req.assigned_at = req.updated_at
    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/complete ─────────────────────────────────────


@router.post("/requests/{request_id}/complete", response_model=TattooRequestOut)
async def complete_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Завершить сеанс (scheduled → completed)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    _validate_transition(req.status, "completed")

    if not req.appointment:
        raise BadRequestError("У заявки нет активной записи")

    req.appointment.status = "done"
    req.status = "completed"
    req.completed_at = req.updated_at
    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/cancel ──────────────────────────────────────


@router.post("/requests/{request_id}/cancel", response_model=TattooRequestOut)
async def cancel_appointment(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Отменить запись (scheduled → cancelled, appointment → cancelled)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    if not req.appointment:
        raise BadRequestError("У заявки нет активной записи")

    # Отменяем appointment
    req.appointment.status = "cancelled"

    # Возвращаем заявку в new
    if req.status == "scheduled":
        req.status = "new"

    await session.commit()
    return req


# ─── POST /api/v1/requests/{id}/reactivate ──────────────────────────────────


@router.post("/requests/{request_id}/reactivate", response_model=TattooRequestOut)
async def reactivate_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    req: TattooRequest = Depends(owner_of_request),
    _admin: dict = Depends(admin_only),
):
    """Возобновить заявку из rejected (rejected → new)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
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

    if req.status != "rejected":
        raise InvalidTransitionError(f"Заявка не в статусе rejected (текущий: {req.status})")

    req.status = "new"
    req.rejection_reason = None
    req.rejected_at = None
    req.queue_order = None
    req.queue_rank = None
    await session.commit()
    return req


# ─── GET /api/v1/trash ──────────────────────────────────────────────────────


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
        .where(
            TattooRequest.status.in_(["completed", "rejected", "cancelled"]),
        )
        .order_by(TattooRequest.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ─── DELETE /api/v1/trash/{id} ──────────────────────────────────────────────


@router.delete("/trash/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_from_trash(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
    req: TattooRequest = Depends(owner_of_request),
):
    """Удалить заявку из корзины (mark as archived + remove appointment)."""
    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .with_for_update()
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        raise RequestNotFoundError()

    req.is_archived = True
    await session.commit()
