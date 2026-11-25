"""Calendar slots management."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin_only
from app.database import get_db
from app.dependencies import ConflictError
from app.models import MasterSlot, Appointment
from app.schemas import MasterSlotCreate, MasterSlotOut

router = APIRouter(tags=["slots"])


@router.get("/slots", response_model=list[MasterSlotOut])
async def list_slots(
    start_date: str | None = Query(None, alias="start_date"),
    end_date: str | None = Query(None, alias="end_date"),
    limit: int = Query(60, le=180),
    session: AsyncSession = Depends(get_db),
):
    """Список слотов с фильтрацией по дате."""
    if start_date:
        sd = date.fromisoformat(start_date)
    else:
        sd = date.today()

    if end_date:
        ed = date.fromisoformat(end_date)
    else:
        ed = sd + timedelta(days=limit)

    stmt = (
        select(MasterSlot)
        .where(
            and_(
                MasterSlot.slot_date >= sd,
                MasterSlot.slot_date <= ed,
            )
        )
        .order_by(MasterSlot.slot_date)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/slots/{date}", response_model=MasterSlotOut, status_code=201
)
async def create_slot(
    date_str: str,
    data: MasterSlotCreate | None = None,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Создать новый слот."""
    slot_date = date.fromisoformat(date_str)
    data = data or MasterSlotCreate(slot_date=slot_date)

    if data.slot_date != slot_date:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Дата в URL и теле должны совпадать")

    existing = await session.execute(
        select(MasterSlot).where(MasterSlot.slot_date == slot_date)
    )
    if existing.scalar_one_or_none():
        raise ConflictError(f"Слот на {slot_date} уже существует")

    slot = MasterSlot(
        slot_date=data.slot_date,
        is_blocked=data.is_blocked,
        master_note=data.master_note,
    )
    session.add(slot)
    await session.commit()
    return slot


@router.post("/slots/{date}/toggle", response_model=MasterSlotOut)
async def toggle_slot(
    date_str: str,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Переключить статус заблокированности слота."""
    slot_date = date.fromisoformat(date_str)

    stmt = select(MasterSlot).where(MasterSlot.slot_date == slot_date)
    result = await session.execute(stmt)
    slot = result.scalar_one_or_none()

    if not slot:
        slot = MasterSlot(slot_date=slot_date, is_blocked=True)
        session.add(slot)
        await session.commit()
        return slot

    slot.is_blocked = not slot.is_blocked
    await session.commit()
    return slot
