"""CRUD + transitions для заявок.

Все эндпоинты защищены Telegram-авторизацией. Клиент не передаёт user_id:
личность берётся из подписанного initData, иначе любой мог бы создать
заявку от чужого имени.
"""

from __future__ import annotations

import logging
from datetime import date as date_type, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    admin_only,
    get_current_user,
    load_request_for_user,
    owner_of_request,
)
from app.database import get_db
from app.bot.services.request_service import (
    cancel_appointment as cancel_request_appointment,
    complete_session,
    transition_status,
)
from app.bot.services.notification_service import NotificationService
from app.dependencies import (
    BadRequestError,
    ConflictError,
    InvalidTransitionError,
    RequestNotFoundError,
)
from app.models import (
    Appointment,
    BotSettings,
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
    try:
        # The savepoint converts two simultaneous first requests from the same
        # Telegram user into one successful insert plus one re-read, instead of
        # leaking a unique-key 500 to the client.
        async with session.begin_nested():
            session.add(
                TgUser(
                    tg_id=user_id,
                    first_name=(data.get("first_name") or "Гость")[:100],
                    last_name=(data.get("last_name") or None),
                    username=(data.get("username") or None),
                )
            )
            await session.flush()
    except IntegrityError:
        existing = await session.execute(select(TgUser).where(TgUser.tg_id == user_id))
        if existing.scalar_one_or_none() is None:
            raise


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
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Создаёт заявку сразу в статусе 'new' (то есть отправленную).

    user_id и created_by намеренно НЕ берутся из тела запроса — только
    из проверенного initData.
    """
    user_id: int = current_user["user_id"]
    await _ensure_user(session, user_id, current_user.get("user"))

    if idempotency_key:
        idempotency_key = idempotency_key.strip()
        if len(idempotency_key) > 100:
            raise HTTPException(status_code=400, detail="Слишком длинный Idempotency-Key")
        existing = (
            await session.execute(
                select(TattooRequest)
                .where(
                    TattooRequest.user_id == user_id,
                    TattooRequest.idempotency_key == idempotency_key,
                )
                .options(*_FULL_OPTIONS)
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    # The surcharge is a server-side price. Never trust a client-submitted
    # amount, otherwise a caller can set it to any value or avoid the price.
    urgent_surcharge = None
    if data.is_urgent:
        settings_row = (
            await session.execute(select(BotSettings).where(BotSettings.id == 1))
        ).scalar_one_or_none()
        urgent_surcharge = float(settings_row.urgent_price or 0) if settings_row else 0

    req = TattooRequest(
        user_id=user_id,
        created_by=user_id,
        description=data.description.strip(),
        location=data.location.strip(),
        size=data.size.strip(),
        color_mode=data.color_mode,
        is_urgent=bool(data.is_urgent),
        urgent_surcharge=urgent_surcharge,
        brief_answers=data.brief_answers or None,
        idempotency_key=idempotency_key or None,
        status="new",
    )
    session.add(req)
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent retry may win the unique constraint between the lookup
        # above and commit. Return that request and do not notify twice.
        await session.rollback()
        if idempotency_key:
            existing = (
                await session.execute(
                    select(TattooRequest)
                    .where(
                        TattooRequest.user_id == user_id,
                        TattooRequest.idempotency_key == idempotency_key,
                    )
                    .options(*_FULL_OPTIONS)
                )
            ).scalar_one_or_none()
            if existing:
                return existing
        raise

    # Перечитываем со связями, иначе сериализация упадёт
    created = await _load_locked(session, req.id)
    await _notify_master_new_request(req)
    return created


async def _notify_master_new_request(req: TattooRequest) -> None:
    """Сообщает мастеру о новой заявке. Ошибка не ломает создание."""
    try:
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
        await service.send_request_update(
            req.id,
            settings.master_tg_id,
            text,
            notification_type="request_created",
        )
    except Exception:
        logger.exception("Не удалось уведомить мастера о заявке #%s", req.id)


async def _notify_request_client(
    req: TattooRequest,
    text: str,
    notification_type: str,
) -> None:
    """Notify the request owner after commit; delivery never rolls back data."""
    try:
        from app.main import bot as running_bot

        if running_bot is None or req.user is None:
            logger.warning(
                "Невозможно уведомить клиента по заявке #%s: bot/user unavailable",
                req.id,
            )
            return
        service = NotificationService(running_bot)
        await service.send_request_update(
            req.id,
            req.user.tg_id,
            text,
            notification_type=notification_type,
        )
    except Exception:
        logger.exception("Не удалось уведомить клиента по заявке #%s", req.id)


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
    req = await transition_status(session, request_id, "accepted")
    await session.commit()
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.request_accepted(request_id),
        "request_accepted",
    )
    return result


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
    reason = data.reason if data and data.reason else None
    req = await transition_status(
        session,
        request_id,
        "rejected",
        extra_fields={"rejection_reason": reason},
    )
    await session.commit()
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.request_rejected(request_id, reason),
        "request_rejected",
    )
    return result


@router.post("/requests/{request_id}/proceed", response_model=TattooRequestOut)
async def proceed_to_sketch(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Мастер берётся за эскиз (accepted → in_progress)."""
    req = await transition_status(session, request_id, "in_progress")
    await session.commit()
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.request_in_progress(request_id),
        "request_in_progress",
    )
    return result


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
            select(MasterSlot)
            .where(MasterSlot.slot_date == target_date)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if not slot:
        slot = MasterSlot(slot_date=target_date, is_blocked=False)
        try:
            # Keep the request transaction alive if another worker wins the
            # unique slot_date insert. A plain session.rollback() here would
            # discard the locked request and any preceding changes.
            async with session.begin_nested():
                session.add(slot)
                await session.flush()
        except IntegrityError:
            # Another request created this date concurrently. The savepoint
            # has been rolled back; lock and reuse the existing slot.
            req = await _load_locked(session, request_id)
            slot = (
                await session.execute(
                    select(MasterSlot)
                    .where(MasterSlot.slot_date == target_date)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if slot is None:
                raise ConflictError("Не удалось создать слот, повторите попытку")

    if slot.is_blocked:
        raise ConflictError(f"Дата {target_date} закрыта мастером")

    busy = await session.execute(
        select(Appointment).where(
            Appointment.slot_id == slot.id,
            Appointment.status.in_(["confirmed", "done"]),
        )
    )
    if busy.scalar_one_or_none():
        raise ConflictError(f"На дату {target_date} уже есть активная запись")

    appointment = req.appointment
    if appointment is not None:
        if appointment.status in ("confirmed", "done"):
            raise ConflictError("У заявки уже есть активная запись")
        # Reuse the existing row after cancellation because request_id is unique.
        appointment.slot_id = slot.id
        appointment.status = "confirmed"
    else:
        appointment = Appointment(
            request_id=req.id,
            slot_id=slot.id,
            status="confirmed",
        )
        session.add(appointment)
    # The session deliberately uses autoflush=False. Persist the reused (or
    # newly created) appointment before transition_status refreshes the locked
    # request with populate_existing, otherwise a cancelled historical row can
    # overwrite this in-memory confirmed state.
    await session.flush()
    await transition_status(session, request_id, "scheduled")
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("На эту дату уже назначен другой сеанс") from exc
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.appointment_scheduled(
            request_id, target_date.isoformat()
        ),
        "appointment_scheduled",
    )
    return result


@router.post("/requests/{request_id}/complete", response_model=TattooRequestOut)
async def complete_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Завершить сеанс (scheduled → completed)."""
    req = await complete_session(session, request_id)
    await session.commit()
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.appointment_completed(request_id),
        "appointment_completed",
    )
    return result


@router.post("/requests/{request_id}/cancel", response_model=TattooRequestOut)
async def cancel_appointment(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Отменить запись, вернуть заявку в очередь."""
    req = await cancel_request_appointment(session, request_id)
    await session.commit()
    result = await _load_locked(session, request_id)
    await _notify_request_client(
        result,
        NotificationService.appointment_cancelled(request_id),
        "appointment_cancelled",
    )
    return result


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
        .where(TattooRequest.is_archived == False)  # noqa: E712
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

    if req.status not in ("completed", "rejected", "cancelled"):
        raise BadRequestError("В корзину можно убрать только закрытую заявку")

    req.is_archived = True
    await session.commit()
