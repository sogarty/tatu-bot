"""Календарь: слоты мастера.

GET /slots — публичный (клиент смотрит свободные даты).
POST /slots/... — только мастер.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin_only
from app.database import get_db
from app.dependencies import ConflictError
from app.models import Appointment, MasterSlot
from app.schemas import MasterSlotCreate, MasterSlotOut, MasterSlotUpdate

router = APIRouter(tags=["slots"])

MAX_HORIZON_DAYS = 366


@router.get("/slots", response_model=list[MasterSlotOut])
async def list_slots(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    limit: int = Query(60, le=180),
    session: AsyncSession = Depends(get_db),
):
    """Слоты за период. Без параметров — начиная с сегодня."""
    try:
        sd = date.fromisoformat(start_date) if start_date else date.today()
        ed = date.fromisoformat(end_date) if end_date else sd + timedelta(days=limit)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Дата должна быть в формате ГГГГ-ММ-ДД"
        )

    if ed < sd:
        raise HTTPException(status_code=400, detail="Дата окончания раньше начала")

    if (ed - sd).days > MAX_HORIZON_DAYS:
        ed = sd + timedelta(days=MAX_HORIZON_DAYS)

    stmt = (
        select(MasterSlot)
        .where(MasterSlot.slot_date >= sd, MasterSlot.slot_date <= ed)
        .order_by(MasterSlot.slot_date)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/slots/availability")
async def availability(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
):
    """Свободные и занятые даты одним ответом — для календаря клиента."""
    try:
        sd = date.fromisoformat(start_date) if start_date else date.today()
        ed = date.fromisoformat(end_date) if end_date else sd + timedelta(days=60)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Дата должна быть в формате ГГГГ-ММ-ДД"
        )

    if ed < sd:
        raise HTTPException(status_code=400, detail="Дата окончания раньше начала")

    if (ed - sd).days > MAX_HORIZON_DAYS:
        ed = sd + timedelta(days=MAX_HORIZON_DAYS)

    slots = list(
        (
            await session.execute(
                select(MasterSlot)
                .where(MasterSlot.slot_date >= sd, MasterSlot.slot_date <= ed)
                .order_by(MasterSlot.slot_date)
            )
        ).scalars()
    )

    booked = {
        row[0]
        for row in (
            await session.execute(
                select(MasterSlot.slot_date)
                .join(Appointment, Appointment.slot_id == MasterSlot.id)
                .where(
                    MasterSlot.slot_date >= sd,
                    MasterSlot.slot_date <= ed,
                    Appointment.status.in_(["confirmed", "done"]),
                )
            )
        ).all()
    }

    days = []
    for slot in slots:
        days.append(
            {
                "date": slot.slot_date.isoformat(),
                "is_blocked": bool(slot.is_blocked),
                "is_booked": slot.slot_date in booked,
                "master_note": slot.master_note,
            }
        )

    return {"days": days}


@router.post("/slots", response_model=MasterSlotOut, status_code=201)
async def create_slot(
    data: MasterSlotCreate,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Создать слот на дату."""
    existing = await session.execute(
        select(MasterSlot).where(MasterSlot.slot_date == data.slot_date)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"Слот на {data.slot_date} уже существует")

    slot = MasterSlot(
        slot_date=data.slot_date,
        is_blocked=data.is_blocked,
        master_note=data.master_note,
    )
    session.add(slot)
    await session.commit()
    await session.refresh(slot)
    return slot


@router.post("/slots/{slot_date}/toggle", response_model=MasterSlotOut)
async def toggle_slot(
    slot_date: date,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Переключить «занято/свободно». Если слота нет — создаёт занятым."""
    slot = (
        await session.execute(
            select(MasterSlot).where(MasterSlot.slot_date == slot_date)
        )
    ).scalar_one_or_none()

    if not slot:
        slot = MasterSlot(slot_date=slot_date, is_blocked=True)
        session.add(slot)
        await session.commit()
        await session.refresh(slot)
        return slot

    slot.is_blocked = not slot.is_blocked
    await session.commit()
    await session.refresh(slot)
    return slot


@router.patch("/slots/{slot_date}", response_model=MasterSlotOut)
async def update_slot(
    slot_date: date,
    data: MasterSlotUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Изменить заметку или статус слота."""
    slot = (
        await session.execute(
            select(MasterSlot).where(MasterSlot.slot_date == slot_date)
        )
    ).scalar_one_or_none()

    if not slot:
        raise HTTPException(status_code=404, detail="Слот не найден")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(slot, field, value)

    await session.commit()
    await session.refresh(slot)
    return slot