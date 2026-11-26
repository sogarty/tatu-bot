"""Regression tests for queue and appointment invariants."""

from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bot.services.queue_service import get_queue_position
from app.bot.services.request_service import (
    cancel_appointment,
    complete_session,
    transition_status,
)
from app.dependencies import InvalidTransitionError
from app.models import Appointment, Base, MasterSlot, TattooRequest, TgUser


def run(coro):
    return asyncio.run(coro)


async def make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def create_request(session, request_id: int, user_id: int) -> TattooRequest:
    if await session.get(TgUser, user_id) is None:
        session.add(
            TgUser(
                tg_id=user_id,
                first_name=f"User {user_id}",
            )
        )
        await session.flush()
    request = TattooRequest(
        id=request_id,
        user_id=user_id,
        created_by=user_id,
        description=f"Request {request_id}",
        location="arm",
        size="10 cm",
        color_mode="bw",
        status="new",
    )
    session.add(request)
    await session.flush()
    return request


def test_scheduling_removes_only_that_request_from_queue():
    async def scenario():
        engine, factory = await make_session()
        async with factory() as session:
            first = await create_request(session, 1, 101)
            second = await create_request(session, 2, 102)
            third = await create_request(session, 3, 103)
            await transition_status(session, first.id, "accepted")
            await transition_status(session, second.id, "accepted")
            await transition_status(session, third.id, "accepted")
            await transition_status(session, second.id, "in_progress")
            await transition_status(session, second.id, "scheduled")
            await session.commit()

            first_position = await get_queue_position(session, first.id)
            third_position = await get_queue_position(session, third.id)
            assert first_position["queue_rank"] == 1
            assert third_position["queue_rank"] == 2
            assert await get_queue_position(session, second.id) is None
        await engine.dispose()

    run(scenario())


def test_cancel_and_complete_require_scheduled_confirmed_appointment():
    async def scenario():
        engine, factory = await make_session()
        async with factory() as session:
            request = await create_request(session, 1, 101)
            with pytest.raises(InvalidTransitionError):
                await cancel_appointment(session, request.id)
            with pytest.raises(InvalidTransitionError):
                await complete_session(session, request.id)

            await transition_status(session, request.id, "accepted")
            await transition_status(session, request.id, "in_progress")
            slot = MasterSlot(slot_date=date(2026, 12, 5), is_blocked=False)
            session.add(slot)
            await session.flush()
            session.add(
                Appointment(
                    request_id=request.id,
                    slot_id=slot.id,
                    status="confirmed",
                )
            )
            await session.flush()
            await transition_status(session, request.id, "scheduled")
            await cancel_appointment(session, request.id)
            await session.commit()

            assert request.status == "new"
            assert request.appointment.status == "cancelled"
        await engine.dispose()

    run(scenario())


def test_cancelled_appointment_can_be_reused_for_rescheduling():
    async def scenario():
        engine, factory = await make_session()
        async with factory() as session:
            request = await create_request(session, 1, 101)
            await transition_status(session, request.id, "accepted")
            await transition_status(session, request.id, "in_progress")
            slot = MasterSlot(slot_date=date(2026, 12, 5), is_blocked=False)
            session.add(slot)
            await session.flush()
            appointment = Appointment(
                request_id=request.id,
                slot_id=slot.id,
                status="confirmed",
            )
            session.add(appointment)
            await session.flush()
            await transition_status(session, request.id, "scheduled")
            await cancel_appointment(session, request.id)
            await session.flush()

            appointment.status = "confirmed"
            await session.flush()
            await transition_status(session, request.id, "accepted")
            await transition_status(session, request.id, "in_progress")
            await transition_status(session, request.id, "scheduled")

            assert request.status == "scheduled"
            assert appointment.status == "confirmed"
        await engine.dispose()

    run(scenario())
