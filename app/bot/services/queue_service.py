"""Сервис управления очередью заявок. P0-3: advisory lock / FOR UPDATE."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TattooRequest


async def get_next_queue_rank(session: AsyncSession) -> int:
    """
    Атомарное получение следующего номера в очереди.
    P0-3: используем SELECT ... FOR UPDATE (работает в PostgreSQL, игнорируется в SQLite).
    """
    # PostgreSQL advisory lock (игнорируется в SQLite)
    try:
        await session.execute(text(
            "SELECT pg_advisory_xact_lock(74562)"
        ))
    except Exception:
        # SQLite не поддерживает advisory locks — продолжаем без них
        pass

    # Подсчитываем active заявки со статусом accepted, in_progress, scheduled
    result = await session.execute(text(
        """
        SELECT COALESCE(MAX(queue_rank), 0) + 1
        FROM tattoo_request
        WHERE status IN ('accepted', 'in_progress', 'scheduled')
          AND queue_rank IS NOT NULL
          AND is_archived = FALSE
        """
    ))
    row = result.scalar()
    return int(row) if row else 1


async def add_to_queue(
    session: AsyncSession,
    request_id: int,
) -> int:
    """Добавляет заявку в очередь. Возвращает queue_rank."""
    rank = await get_next_queue_rank(session)

    stmt = (
        text(
            "UPDATE tattoo_request "
            "SET queue_rank = :rank, queue_order = :order, "
            "updated_at = NOW() "
            "WHERE id = :request_id"
        )
        .bindparams(request_id=request_id, rank=rank, order=rank)
    )
    await session.execute(stmt)
    await session.flush()
    return rank


async def remove_from_queue(
    session: AsyncSession,
    request_id: int,
) -> None:
    """Удаляет заявку из очереди и пересчитывает ranks."""
    stmt = (
        select(TattooRequest)
        .where(
            TattooRequest.status.in_(["accepted", "in_progress", "scheduled"]),
            TattooRequest.queue_rank.isnot(None),
        )
        .order_by(TattooRequest.queue_rank)
        .with_for_update()  # P0-3: блокировка
    )
    result = await session.execute(stmt)
    requests = result.scalars().all()

    removed_rank = None
    for req in requests:
        if req.id == request_id:
            removed_rank = req.queue_rank
            req.queue_rank = None
            req.queue_order = None
        else:
            if req.queue_rank and removed_rank and req.queue_rank > removed_rank:
                req.queue_rank -= 1

    await session.flush()


async def recalculate_ranks(session: AsyncSession) -> None:
    """Пересчитывает queue_rank для всех активных заявок."""
    stmt = (
        select(TattooRequest)
        .where(
            TattooRequest.status.in_(["accepted", "in_progress", "scheduled"]),
            TattooRequest.queue_rank.isnot(None),
        )
        .order_by(TattooRequest.queue_rank)
        .with_for_update()  # P0-3: блокировка
    )
    result = await session.execute(stmt)
    requests = result.scalars().all()

    for i, req in enumerate(requests, start=1):
        req.queue_rank = i
        req.queue_order = i

    await session.flush()


async def clear_queue_for_scheduled(
    session: AsyncSession,
    scheduled_request_id: int,
) -> None:
    """
    Очистка очереди для всех accepted заявок с queue_rank > 1.
    Вызывается при переходе in_progress → scheduled.
    """
    stmt = text(
        """
        UPDATE tattoo_request
        SET queue_order = NULL, queue_rank = NULL, updated_at = NOW()
        WHERE status = 'accepted'
          AND queue_rank IS NOT NULL
          AND queue_rank > 1
          AND is_archived = FALSE
        """
    )
    await session.execute(stmt)
    await session.flush()


async def get_queue_position(session: AsyncSession, request_id: int) -> dict | None:
    """Возвращает позицию заявки в очереди."""
    result = await session.execute(
        select(TattooRequest).where(TattooRequest.id == request_id)
    )
    req = result.scalar_one_or_none()
    if not req or req.queue_rank is None:
        return None

    # Считаем сколько заявок перед ней в очереди
    count_result = await session.execute(text(
        """
        SELECT COUNT(*)
        FROM tattoo_request
        WHERE status IN ('accepted', 'in_progress', 'scheduled')
          AND queue_rank IS NOT NULL
          AND queue_rank < :rank
          AND is_archived = FALSE
        """
    ).bindparams(rank=req.queue_rank))

    return {
        "request_id": request_id,
        "queue_rank": req.queue_rank,
        "queue_order": req.queue_order,
        "status": req.status,
    }
