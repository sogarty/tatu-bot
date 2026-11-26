"""Сервис управления слотами календаря."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ConflictError
from app.models import Appointment, MasterSlot, TattooRequest
from app.schemas import MasterSlotCreate, MasterSlotUpdate


async def get_slots(
    session: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 60,
) -> list[MasterSlot]:
    """Получает список слотов с фильтрацией по дате."""
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date + timedelta(days=limit)

    stmt = (
        select(MasterSlot)
        .where(
            and_(
                MasterSlot.slot_date >= start_date,
                MasterSlot.slot_date <= end_date,
            )
        )
        .order_by(MasterSlot.slot_date)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_slot_by_date(
    session: AsyncSession,
    slot_date: date,
) -> MasterSlot | None:
    """Получает слот по дате."""
    stmt = select(MasterSlot).where(MasterSlot.slot_date == slot_date)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_slot(
    session: AsyncSession,
    data: MasterSlotCreate,
) -> MasterSlot:
    """Создаёт новый слот."""
    existing = await get_slot_by_date(session, data.slot_date)
    if existing:
        raise ConflictError(
            f"Слот на {data.slot_date} уже существует"
        )

    slot = MasterSlot(
        slot_date=data.slot_date,
        is_blocked=data.is_blocked,
        master_note=data.master_note,
    )
    session.add(slot)
    await session.flush()
    return slot


async def toggle_slot(
    session: AsyncSession,
    slot_date: date,
) -> MasterSlot:
    """Переключает статус заблокированности слота."""
    stmt = (
        select(MasterSlot)
        .where(MasterSlot.slot_date == slot_date)
        .with_for_update()
    )
    result = await session.execute(stmt)
    slot = result.scalar_one_or_none()

    if not slot:
        # Создаём слот
        slot = MasterSlot(
            slot_date=slot_date,
            is_blocked=True,
        )
        session.add(slot)
        await session.flush()
        return slot

    slot.is_blocked = not slot.is_blocked
    await session.flush()
    return slot


async def update_slot(
    session: AsyncSession,
    slot_date: date,
    data: MasterSlotUpdate,
) -> MasterSlot:
    """Обновляет поля слота."""
    stmt = (
        select(MasterSlot)
        .where(MasterSlot.slot_date == slot_date)
        .with_for_update()
    )
    result = await session.execute(stmt)
    slot = result.scalar_one_or_none()

    if not slot:
        raise ConflictError(f"Слот на {slot_date} не найден")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(slot, field, value)

    await session.flush()
    return slot


async def get_free_slots(
    session: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 30,
) -> list[date]:
    """Возвращает список свободных дат (без appointment со статусом confirmed/done)."""
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date + timedelta(days=limit)

    # Получаем все слоты в диапазоне
    stmt = select(MasterSlot).where(
        and_(
            MasterSlot.slot_date >= start_date,
            MasterSlot.slot_date <= end_date,
        )
    )
    result = await session.execute(stmt)
    slots = result.scalars().all()

    if not slots:
        # Если слотов нет — все дни считаются свободными
        return _generate_date_range(start_date, end_date)

    # Получаем даты с appointment в статусе confirmed/done
    appointment_stmt = select(Appointment.slot_id).where(
        Appointment.status.in_(["confirmed", "done"])
    )
    ap_result = await session.execute(appointment_stmt)
    booked_slot_ids = {row[0] for row in ap_result.all()}

    booked_dates = set()
    for slot in slots:
        if slot.id in booked_slot_ids or slot.is_blocked:
            booked_dates.add(slot.slot_date)

    # Свободные даты — все слоты минус забронированные
    free_dates = set()
    for slot in slots:
        if slot.slot_date not in booked_dates:
            free_dates.add(slot.slot_date)

    # Добавляем даты без слотов
    all_dates = _generate_date_range(start_date, end_date)
    for d in all_dates:
        if d not in booked_dates:
            free_dates.add(d)

    return sorted(free_dates)


async def get_booked_dates(
    session: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 30,
) -> list[date]:
    """Возвращает даты с подтверждёнными/завершёнными записями."""
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date + timedelta(days=limit)

    stmt = (
        select(MasterSlot.slot_date)
        .join(
            Appointment,
            MasterSlot.id == Appointment.slot_id,
        )
        .where(
            and_(
                MasterSlot.slot_date >= start_date,
                MasterSlot.slot_date <= end_date,
                Appointment.status.in_(["confirmed", "done"]),
            )
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _generate_date_range(start: date, end: date) -> list[date]:
    """Генерирует список дат между start и end включительно."""
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


async def get_appointments_for_slot(
    session: AsyncSession,
    slot_id: int,
) -> list[Appointment]:
    """Получает все записи для слота."""
    stmt = select(Appointment).where(Appointment.slot_id == slot_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
