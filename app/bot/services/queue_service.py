"""Управление очередью заявок.

Переписано на ORM вместо raw SQL: прежние запросы использовали NOW() и
FALSE из PostgreSQL и падали бы на SQLite ("no such function: NOW").
Здесь используются func.now() и булевы значения SQLAlchemy, поэтому код
одинаково работает и на SQLite, и на PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TattooRequest

# A scheduled request owns a calendar appointment, not a queue position.
ACTIVE_STATUSES = ("accepted", "in_progress")


async def _advisory_lock(session: AsyncSession) -> None:
    """Защита от гонки при выдаче номера в очереди.

    Работает только в PostgreSQL (advisory lock). На SQLite блокировка
    отсутствует — там запись всё равно сериализуется самой СУБД.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    # A failed lock is a correctness failure, not a recoverable warning. If
    # PostgreSQL cannot provide serialization, the caller must roll back rather
    # than assign duplicate queue positions.
    await session.execute(text("SELECT pg_advisory_xact_lock(74562)"))


async def get_next_queue_rank(session: AsyncSession) -> int:
    """Возвращает следующий свободный номер в очереди."""
    await _advisory_lock(session)

    result = await session.execute(
        select(func.coalesce(func.max(TattooRequest.queue_rank), 0) + 1).where(
            TattooRequest.status.in_(ACTIVE_STATUSES),
            TattooRequest.queue_rank.is_not(None),
            TattooRequest.is_archived.is_(False),
        )
    )
    return int(result.scalar() or 1)


async def add_to_queue(session: AsyncSession, request_id: int) -> int:
    """Ставит заявку в очередь и возвращает её номер."""
    rank = await get_next_queue_rank(session)

    req = await session.get(TattooRequest, request_id)
    if req is None:
        raise ValueError(f"Заявка {request_id} не найдена")

    req.queue_rank = rank
    req.queue_order = rank
    req.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    return rank


async def remove_from_queue(session: AsyncSession, request_id: int) -> None:
    """Убирает заявку из очереди и сдвигает номера остальных."""
    result = await session.execute(
        select(TattooRequest)
        .where(
            TattooRequest.status.in_(ACTIVE_STATUSES),
            TattooRequest.queue_rank.is_not(None),
        )
        .order_by(TattooRequest.queue_rank)
        .with_for_update()
    )
    requests = list(result.scalars().all())

    removed = next((req for req in requests if req.id == request_id), None)
    if removed is None:
        return

    # Move ranks out of the unique-index domain before compacting. Updating
    # rank 2 to rank 1 while rank 1 still exists would otherwise violate the
    # partial unique index on PostgreSQL.
    for index, req in enumerate(requests, start=1):
        req.queue_rank = -index
        req.queue_order = -index
    await session.flush()

    next_rank = 1
    for req in requests:
        if req.id == request_id:
            req.queue_rank = None
            req.queue_order = None
            continue
        req.queue_rank = next_rank
        req.queue_order = next_rank
        next_rank += 1

    await session.flush()


async def recalculate_ranks(session: AsyncSession) -> None:
    """Перенумеровывает очередь подряд: 1, 2, 3 …"""
    result = await session.execute(
        select(TattooRequest)
        .where(
            TattooRequest.status.in_(ACTIVE_STATUSES),
            TattooRequest.queue_rank.is_not(None),
        )
        .order_by(TattooRequest.queue_rank)
        .with_for_update()
    )
    requests = list(result.scalars().all())
    for i, req in enumerate(requests, start=1):
        req.queue_rank = -i
        req.queue_order = -i
    await session.flush()

    for i, req in enumerate(requests, start=1):
        req.queue_rank = i
        req.queue_order = i

    await session.flush()


async def get_queue_position(
    session: AsyncSession, request_id: int
) -> dict | None:
    """Позиция заявки в очереди или None, если она вне очереди."""
    req = await session.get(TattooRequest, request_id)
    if req is None or req.queue_rank is None:
        return None

    ahead = await session.execute(
        select(func.count())
        .select_from(TattooRequest)
        .where(
            TattooRequest.status.in_(ACTIVE_STATUSES),
            TattooRequest.queue_rank.is_not(None),
            TattooRequest.queue_rank < req.queue_rank,
            TattooRequest.is_archived.is_(False),
        )
    )

    return {
        "request_id": request_id,
        "queue_rank": req.queue_rank,
        "queue_order": req.queue_order,
        "status": req.status,
        "ahead": int(ahead.scalar() or 0),
    }
