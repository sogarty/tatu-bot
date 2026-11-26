"""Admin handlers: /admin, manage requests, calendar."""

from __future__ import annotations

from datetime import date, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    get_admin_main_keyboard,
    get_request_actions_keyboard,
    get_calendar_keyboard,
)
from app.bot.services.notification_service import NotificationService
from app.bot.services.request_service import (
    get_request_by_id,
    transition_status,
    reset_rejection,
    cancel_appointment,
    complete_session,
)
from app.bot.services.calendar_service import (
    get_booked_dates,
    get_free_slots,
    get_slot_by_date,
    create_slot,
)
from app.config import get_settings
from app.models import MasterWhitelist, TattooRequest

router = Router(name="admin")


def register_handlers(dp):
    dp.include_router(router)

    # Command handlers
    router.message.register(cmd_admin, Command("admin"))
    router.message.register(cmd_add_master, Command("add_master"))
    router.message.register(cmd_remove_master, Command("remove_master"))

    # Callback handlers
    router.callback_query.register(
        handle_admin_requests, F.data == "admin:requests"
    )
    router.callback_query.register(
        handle_admin_calendar, F.data == "admin:calendar"
    )
    router.callback_query.register(
        handle_admin_settings, F.data == "admin:settings"
    )
    router.callback_query.register(
        handle_admin_trash, F.data == "admin:trash"
    )

    # Request actions
    router.callback_query.register(
        handle_admin_request_view, F.data.startswith("admin:req_view:")
    )
    router.callback_query.register(
        handle_accept_request, F.data.startswith("req_accept:")
    )
    router.callback_query.register(
        handle_reject_request, F.data.startswith("req_reject:")
    )
    router.callback_query.register(
        handle_proceed_request, F.data.startswith("req_proceed:")
    )
    router.callback_query.register(
        handle_schedule_request, F.data.startswith("req_schedule:")
    )
    router.callback_query.register(
        handle_complete_request, F.data.startswith("req_complete:")
    )
    router.callback_query.register(
        handle_cancel_request, F.data.startswith("req_cancel:")
    )
    router.callback_query.register(
        handle_reactivate_request, F.data.startswith("req_reactivate:")
    )
    router.callback_query.register(
        handle_return_new, F.data.startswith("req_return_new:")
    )
    router.callback_query.register(
        handle_return_accepted, F.data.startswith("req_return_accepted:")
    )

    # Calendar navigation (handle_calendar_nav обрабатывает и prev, и next)
    router.callback_query.register(
        handle_calendar_select, F.data.startswith("cal_select:")
    )


# ─── Commands ────────────────────────────────────────────────────────────────


@router.message(Command("admin"))
async def cmd_admin(message: Message, session: AsyncSession):
    """Вход в админ-панель."""
    user_id = message.from_user.id
    settings = get_settings()

    # Проверяем whitelist
    result = await session.execute(
        select(MasterWhitelist).where(MasterWhitelist.tg_id == user_id)
    )
    is_master = result.scalar_one_or_none()

    if not is_master and user_id != settings.master_tg_id:
        await message.answer("🔒 Доступ запрещён.")
        return

    # Показываем сводку
    result = await session.execute(
        select(TattooRequest.status)
        .where(TattooRequest.is_archived == False)
    )
    statuses = [row[0] for row in result.all()]

    from collections import Counter
    counts = Counter(statuses)

    dashboard_text = (
        f"👋 Добро пожаловать, мастер!\n\n"
        f"📊 <b>Сводка:</b>\n"
        f"⏳ В очереди: {counts.get('new', 0)}\n"
        f"✅ Принято: {counts.get('accepted', 0)}\n"
        f"🖌 Эскиз: {counts.get('in_progress', 0)}\n"
        f"📅 Записана: {counts.get('scheduled', 0)}\n"
        f"✨ Завершена: {counts.get('completed', 0)}\n"
        f"❌ Отклонена: {counts.get('rejected', 0)}"
    )

    await message.answer(
        dashboard_text,
        reply_markup=get_admin_main_keyboard(),
    )


@router.message(Command("add_master"))
async def cmd_add_master(
    message: Message,
    session: AsyncSession,
    command: Command,
):
    """Добавить мастера в whitelist."""
    args = command.args
    if not args:
        await message.answer(
            "Использование: /add_master {tg_id}"
        )
        return

    try:
        tg_id = int(args)
    except ValueError:
        await message.answer("❌ Укажите числовой tg_id")
        return

    result = await session.execute(
        select(MasterWhitelist).where(MasterWhitelist.tg_id == tg_id)
    )
    if result.scalar_one_or_none():
        await message.answer(f"❌ Мастер {tg_id} уже в whitelist")
        return

    entry = MasterWhitelist(tg_id=tg_id)
    session.add(entry)
    await message.answer(f"✅ Мастер {tg_id} добавлен в whitelist")


@router.message(Command("remove_master"))
async def cmd_remove_master(
    message: Message,
    session: AsyncSession,
    command: Command,
):
    """Убрать мастера из whitelist."""
    args = command.args
    if not args:
        await message.answer("Использование: /remove_master {tg_id}")
        return

    try:
        tg_id = int(args)
    except ValueError:
        await message.answer("❌ Укажите числовой tg_id")
        return

    result = await session.execute(
        select(MasterWhitelist).where(MasterWhitelist.tg_id == tg_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        await message.answer(f"❌ Мастер {tg_id} не найден в whitelist")
        return

    await session.delete(entry)
    await message.answer(f"✅ Мастер {tg_id} удалён из whitelist")


# ─── Admin Request List ─────────────────────────────────────────────────────


@router.callback_query(F.data == "admin:requests")
async def handle_admin_requests(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Показывает список активных заявок."""
    result = await session.execute(
        select(TattooRequest)
        .where(
            TattooRequest.status.in_(
                ["new", "accepted", "in_progress", "scheduled", "rejected"]
            ),
            TattooRequest.is_archived == False,
        )
        .order_by(TattooRequest.created_at.desc())
        .limit(20)
    )
    requests = list(result.scalars().all())

    if not requests:
        await query.message.edit_text(
            "📋 Активных заявок пока нет.",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    lines = ["📋 <b>Активные заявки:</b>\n"]
    for req in requests:
        status_emoji = {
            "new": "⏳",
            "accepted": "✅",
            "in_progress": "🖌",
            "scheduled": "📅",
            "rejected": "❌",
        }.get(req.status, "")
        lines.append(
            f"  #{req.id} {status_emoji} <i>{req.status}</i>"
        )

    lines.append("\n  Выбери заявку для действий:")
    for req in requests[:5]:
        lines.append(
            f"  [#{req.id}] ({req.status})"
        )

    # Создаём кнопки для каждой заявки
    buttons = []
    for req in requests[:5]:
        buttons.append([
            InlineKeyboardButton(
                text=f"#{req.id} ({req.status})",
                callback_data=f"admin:req_view:{req.id}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text="← Назад",
            callback_data="admin:back",
        )
    ])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await query.message.edit_text(
        "\n".join(lines),
        reply_markup=keyboard,
    )
    await query.answer()


# ─── Admin Request View ─────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("admin:req_view:"))
async def handle_admin_request_view(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Показывает детальную карточку заявки."""
    request_id = int(query.data.split(":")[2])
    try:
        from app.bot.services.request_service import get_request_by_id
        req = await get_request_by_id(session, request_id)

        status_emoji = {
            "new": "⏳",
            "accepted": "✅",
            "in_progress": "🖌",
            "scheduled": "📅",
            "rejected": "❌",
            "cancelled": "🚫",
            "completed": "✨",
            "draft": "📝",
        }
        emoji = status_emoji.get(req.status, "")

        user_name = f"@{req.creator.username}" if req.creator.username else req.creator.first_name
        if req.creator.last_name:
            user_name += f" {req.creator.last_name}"

        text = (
            f"📋 <b>Заявка #{req.id} {emoji}</b>\n\n"
            f"👤 <b>{user_name}</b>\n"
            f"📅 Создана: {req.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"💬 <i>{req.description[:100]}{'...' if len(req.description) > 100 else ''}</i>\n\n"
            f"📍 Место: {req.location}\n"
            f"📏 Размер: {req.size}\n"
            f"🎨 Цвет: {'Ч/Б' if req.color_mode == 'bw' else 'Цветная'}\n"
            f"⚡ Срочность: {'Да' if req.is_urgent else 'Нет'}\n"
        )

        if req.appointment:
            text += f"📅 Сеанс: {req.appointment.slot.slot_date.strftime('%d.%m.%Y')}\n"

        await query.message.edit_text(
            text,
            reply_markup=get_request_actions_keyboard(request_id, req.status),
        )
        await query.answer()
    except Exception as e:
        await query.answer(f"Ошибка: {e}")
        await query.message.edit_text(
            f"❌ Не удалось открыть заявку #{request_id}",
            reply_markup=get_admin_main_keyboard(),
        )


# ─── Request Actions ────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("req_accept:"))
async def handle_accept_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Мастер принимает заявку (new → accepted)."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await transition_status(session, request_id, "accepted")
        await query.message.edit_text(
            f"✅ Заявка #{request_id} принята!",
            reply_markup=get_request_actions_keyboard(request_id, "accepted"),
        )
        await query.answer("Заявка принята ✅")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_reject:"))
async def handle_reject_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Мастер отклоняет заявку."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await transition_status(session, request_id, "rejected")
        await query.message.edit_text(
            f"❌ Заявка #{request_id} отклонена.",
            reply_markup=get_request_actions_keyboard(request_id, "rejected"),
        )
        await query.answer("Заявка отклонена ❌")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_proceed:"))
async def handle_proceed_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Мастер берётся за эскиз (accepted → in_progress)."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await transition_status(session, request_id, "in_progress")
        await query.message.edit_text(
            f"🖌 Заявка #{request_id} — мастер берётся за эскиз!",
            reply_markup=get_request_actions_keyboard(request_id, "in_progress"),
        )
        await query.answer("Берусь за эскиз 🖌")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_schedule:"))
async def handle_schedule_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Мастер назначает дату (in_progress → scheduled)."""
    request_id = int(query.data.split(":")[1])
    today = date.today()
    end_date = today + timedelta(days=30)
    booked = await get_booked_dates(session, today, end_date)
    kb = get_calendar_keyboard(
        year=today.year,
        month=today.month,
        booked_dates=[d.isoformat() for d in booked],
        current_date=today.isoformat(),
    )
    await query.message.edit_text(
        f"📅 Выбери дату для заявки #{request_id}:",
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("req_complete:"))
async def handle_complete_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Завершение сеанса (scheduled → completed)."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await complete_session(session, request_id)
        await query.message.edit_text(
            f"✨ Заявка #{request_id} завершена!",
            reply_markup=get_admin_main_keyboard(),
        )
        await query.answer("Сеанс завершён ✨")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_cancel:"))
async def handle_cancel_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Отмена записи (scheduled → cancelled). P0-7: мгновенно."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await cancel_appointment(session, request_id)
        await query.message.edit_text(
            f"🚫 Запись по заявке #{request_id} отменена.",
            reply_markup=get_admin_main_keyboard(),
        )
        await query.answer("Запись отменена")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_reactivate:"))
async def handle_reactivate_request(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Возобновление из rejected (rejected → new)."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await reset_rejection(session, request_id)
        await query.message.edit_text(
            f"↩️ Заявка #{request_id} возобновлена.",
            reply_markup=get_request_actions_keyboard(request_id, "new"),
        )
        await query.answer("Заявка возобновлена")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_return_new:"))
async def handle_return_new(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Возврат заявки в new."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await transition_status(session, request_id, "new")
        await query.message.edit_text(
            f"↩️ Заявка #{request_id} возвращена в new.",
            reply_markup=get_request_actions_keyboard(request_id, "new"),
        )
        await query.answer("Возвращено в new")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


@router.callback_query(F.data.startswith("req_return_accepted:"))
async def handle_return_accepted(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Возврат заявки в accepted."""
    request_id = int(query.data.split(":")[1])
    try:
        req = await transition_status(session, request_id, "accepted")
        await query.message.edit_text(
            f"↩️ Заявка #{request_id} возвращена в accepted.",
            reply_markup=get_request_actions_keyboard(request_id, "accepted"),
        )
        await query.answer("Возвращено в accepted")
    except Exception as e:
        await query.answer(f"Ошибка: {e}")


# ─── Admin Calendar ─────────────────────────────────────────────────────────


@router.callback_query(F.data == "admin:calendar")
async def handle_admin_calendar(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Показывает календарь."""
    today = date.today()
    end_date = today + timedelta(days=30)
    booked = await get_booked_dates(session, today, end_date)
    kb = get_calendar_keyboard(
        year=today.year,
        month=today.month,
        booked_dates=[d.isoformat() for d in booked],
        current_date=today.isoformat(),
    )
    await query.message.edit_text(
        "📅 <b>Календарь мастера</b>\n\n"
        "● Свободно  ✕ Занято  ◼ Сегодня",
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("cal_prev:"))
@router.callback_query(F.data.startswith("cal_next:"))
async def handle_calendar_nav(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Навигация по календарю."""
    parts = query.data.split(":")
    action = parts[1]
    year = int(parts[2])
    month = int(parts[3])

    if action == "prev":
        if month == 1:
            month = 12
            year -= 1
        else:
            month -= 1
    else:
        if month == 12:
            month = 1
            year += 1
        else:
            month += 1

    today = date.today()
    end_date = today + timedelta(days=30)
    booked = await get_booked_dates(session, today, end_date)
    kb = get_calendar_keyboard(
        year=year,
        month=month,
        booked_dates=[d.isoformat() for d in booked],
        current_date=today.isoformat(),
    )
    await query.message.edit_text(
        "📅 <b>Календарь мастера</b>",
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data.startswith("cal_select:"))
async def handle_calendar_select(
    query: CallbackQuery,
    session: AsyncSession,
):
    """Выбор даты в календаре."""
    date_str = query.data.split(":")[1]
    selected_date = date.fromisoformat(date_str)

    # Проверяем, свободен ли слот
    slot = await get_slot_by_date(session, selected_date)
    if slot and (slot.is_blocked or await get_booked_dates(session, selected_date, selected_date)):
        await query.answer("Эта дата уже занята ❌")
        return

    await query.message.edit_text(
        f"📅 Вы выбрали дату: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"Нажмите «Назначить дату» для заявки, "
        f"или «← Назад» для отмены.",
        reply_markup=get_admin_main_keyboard(),
    )
    await query.answer(f"Дата: {selected_date.strftime('%d.%m.%Y')}")


# ─── Admin Settings ─────────────────────────────────────────────────────────


@router.callback_query(F.data == "admin:settings")
async def handle_admin_settings(query: CallbackQuery):
    await query.message.edit_text(
        "⚙️ <b>Настройки бота</b>\n\n"
        "💰 Цена за срочность: (из БД)\n"
        "🔗 Портфолио: (из БД)\n"
        "📢 Канал: (из БД)\n\n"
        "Для изменения отправьте команду с новым значением.",
        reply_markup=get_admin_main_keyboard(),
    )
    await query.answer()


# ─── Admin Trash ─────────────────────────────────────────────────────────────


@router.callback_query(F.data == "admin:trash")
async def handle_admin_trash(query: CallbackQuery):
    await query.message.edit_text(
        "🗑 <b>Завершённые заявки</b>\n\n"
        "Здесь отображаются завершённые и отменённые заявки.\n\n"
        "(За последние 30 дней)",
        reply_markup=get_admin_main_keyboard(),
    )
    await query.answer()
