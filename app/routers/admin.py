"""Admin-specific endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import admin_only
from app.database import get_db
from app.models import TattooRequest, MasterWhitelist
from app.schemas import AdminDashboard, WhitelistAdd

router = APIRouter(tags=["admin"])


@router.get("/admin/dashboard", response_model=AdminDashboard)
async def admin_dashboard(
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Дашборд-сводка для администратора."""
    result = await session.execute(
        select(TattooRequest.status)
        .where(TattooRequest.is_archived == False)
    )
    statuses = [row[0] for row in result.all()]

    from collections import Counter
    counts = Counter(statuses)

    return AdminDashboard(
        new_count=counts.get("new", 0),
        accepted_count=counts.get("accepted", 0),
        in_progress_count=counts.get("in_progress", 0),
        scheduled_count=counts.get("scheduled", 0),
        completed_count=counts.get("completed", 0),
        rejected_count=counts.get("rejected", 0),
        total_count=len(statuses),
    )


@router.post("/admin/whitelist/add", status_code=201)
async def add_to_whitelist(
    data: WhitelistAdd,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Добавить мастера в whitelist."""
    existing = await session.execute(
        select(MasterWhitelist).where(MasterWhitelist.tg_id == data.tg_id)
    )
    if existing.scalar_one_or_none():
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Мастер уже в whitelist")

    entry = MasterWhitelist(tg_id=data.tg_id)
    session.add(entry)
    await session.commit()
    return {"tg_id": data.tg_id, "status": "added"}


@router.post("/admin/whitelist/remove")
async def remove_from_whitelist(
    tg_id: int,
    session: AsyncSession = Depends(get_db),
    _admin: dict = Depends(admin_only),
):
    """Убрать мастера из whitelist."""
    result = await session.execute(
        select(MasterWhitelist).where(MasterWhitelist.tg_id == tg_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Мастер не найден в whitelist")

    await session.delete(entry)
    await session.commit()
    return {"tg_id": tg_id, "status": "removed"}
