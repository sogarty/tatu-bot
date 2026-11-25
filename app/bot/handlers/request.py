"""FSM handlers для создания заявки."""

from __future__ import annotations

from aiogram import F, Router, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    get_back_keyboard,
    get_brief_choice_keyboard,
    get_color_keyboard,
    get_exp_keyboard,
    get_important_keyboard,
    get_inspiration_keyboard,
    get_main_keyboard,
    get_request_review_keyboard,
    get_style_keyboard,
    get_urgent_keyboard,
)
from app.bot.services.notification_service import NotificationService
from app.bot.services.request_service import (
    create_draft,
    update_draft,
    finalize_request,
)
from app.config import get_settings
from app.models import (
    BotSettings,
    BriefQuestion,
    RequestReference,
    TattooRequest,
)
from app.schemas import TattooRequestDraftUpdate

router = Router(name="request")


# ─── FSM States ──────────────────────────────────────────────────────────────


class RequestStates(StatesGroup):
    collecting_description = State()
    collecting_references = State()
    collecting_location = State()
    collecting_size = State()
    collecting_color = State()
    collecting_urgent = State()
    collecting_brief_choice = State()
    brief_experienced = State()
    brief_style = State()
    brief_inspiration = State()
    brief_important = State()
    reviewing = State()


def register_handlers(dp):
    dp.include_router(router)

    # ─── Description step ───
    router.message.register(
        handle_collecting_description,
        StateFilter(RequestStates.collecting_description),
    )
    router.callback_query.register(
        handle_request_start,
        F.data == "request_start",
    )

    # ─── References step ───
    router.message.register(
        handle_collecting_references,
        StateFilter(RequestStates.collecting_references),
        F.content_type == F.text,  # Placeholder for photos
    )

    # ─── Color step ───
    router.callback_query.register(
        handle_color_select,
        F.data.in_(["color:bw", "color:color"]),
    )

    # ─── Urgent step ───
    router.callback_query.register(
        handle_urgent_select,
        F.data.in_(["urgent:yes", "urgent:no"]),
    )

    # ─── Brief choice step ───
    router.callback_query.register(
        handle_brief_choice,
        F.data.in_(["brief:fill", "brief:skip"]),
    )

    # ─── Finalization ───
    router.callback_query.register(
        handle_request_finalize,
        F.data == "request_finalized",
    )

    # ─── Brief question handlers ───
    router.callback_query.register(
        handle_brief_experience,
        F.data.startswith("brief_exp:"),
    )
    router.callback_query.register(
        handle_brief_style,
        F.data.startswith("brief_style:"),
    )
    router.callback_query.register(
        handle_brief_inspiration,
        F.data.startswith("brief_insp:"),
    )
    router.callback_query.register(
        handle_brief_important,
        F.data.startswith("brief_important:"),
    )


# ─── Step 1: Description ────────────────────────────────────────────────────


async def handle_request_start(query: CallbackQuery, state: FSMContext):
    """Начало создания заявки."""
    await state.set_state(RequestStates.collecting_description)
    await query.message.answer(
        "✍️ <b>Расскажи о своей идее</b>\n\n"
        "Опиши свою идею максимально подробно:\n"
        "• Что изображено?\n"
        "• Какой вайб / настроение?\n"
        "• Есть ли символы, которые важно включить?\n\n"
        "Чем подробнее — тем точнее будет эскиз 🎨",
    )
    await query.answer()


@router.message(
    StateFilter(RequestStates.collecting_description),
    F.text.length >= 10,
)
async def handle_collecting_description(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Сохраняет описание и переходит к референсам."""
    user_id = message.from_user.id
    description = message.text

    # P0-1: Создаём черновик сразу
    request_id = await _get_or_create_draft(session, user_id)
    await state.update_data(description=description, request_id=request_id)

    await state.set_state(RequestStates.collecting_references)
    await message.answer(
        "📸 <b>Пришли референсы</b>\n\n"
        "Можно прислать от 1 до 5 фото. Пришли их по одной "
        "или сразу все — бот подождёт 📷\n\n"
        "После фото нажми «Далее».",
        reply_markup=get_back_keyboard(),
    )


# ─── Step 2: References ─────────────────────────────────────────────────────


async def handle_collecting_references(
    message: Message,
    state: FSMContext,
):
    """Переход от референсов к шагу местоположения."""
    data = await state.get_data()
    request_id = data.get("request_id")

    await state.set_state(RequestStates.collecting_location)
    await message.answer(
        "📍 <b>Где будет тату?</b>\n\n"
        "Укажи, на какую часть тела будет татуировка:\n\n"
        "Например: «предплечье справа», «ребро», «лопатка».",
        reply_markup=get_back_keyboard(),
    )


# ─── Step 3: Location ───────────────────────────────────────────────────────


@router.message(
    StateFilter(RequestStates.collecting_location),
    F.text.length >= 3,
)
async def handle_collecting_location(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Сохраняет местоположение и переходит к размеру."""
    data = await state.get_data()
    request_id = data.get("request_id")

    # Обновляем черновик в БД
    if request_id:
        await session.execute(
            select(TattooRequest).where(TattooRequest.id == request_id)
        )
        from app.schemas import TattooRequestDraftUpdate
        # Обновляем через ORM
        stmt = select(TattooRequest).where(TattooRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.location = message.text
            await session.flush()

    await state.update_data(location=message.text)
    await state.set_state(RequestStates.collecting_size)
    await message.answer(
        "📏 <b>Какой размер?</b>\n\n"
        "Примерный размер в сантиметрах "
        "(или опиши «примерно с ладонь»)",
        reply_markup=get_back_keyboard(),
    )


# ─── Step 4: Size ────────────────────────────────────────────────────────────


@router.message(StateFilter(RequestStates.collecting_size), F.text)
async def handle_collecting_size(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
):
    """Сохраняет размер и переходит к цвету."""
    data = await state.get_data()
    request_id = data.get("request_id")

    if request_id:
        stmt = select(TattooRequest).where(TattooRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.size = message.text
            await session.flush()

    await state.update_data(size=message.text)
    await state.set_state(RequestStates.collecting_color)
    await message.answer(
        "🎨 <b>Ч/Б или цветная?</b>",
        reply_markup=get_color_keyboard(),
    )


# ─── Step 5: Color ──────────────────────────────────────────────────────────


async def handle_color_select(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Выбор цвета (через inline-кнопку)."""
    color_mode = query.data.split(":", 1)[1]
    data = await state.get_data()
    request_id = data.get("request_id")

    if request_id:
        stmt = select(TattooRequest).where(TattooRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.color_mode = color_mode
            await session.flush()

    await state.update_data(color_mode=color_mode)
    await state.set_state(RequestStates.collecting_urgent)

    settings = get_settings()
    # Получаем цену срочности из настроек
    urgent_price = 0
    result2 = await session.execute(
        select(BotSettings).where(BotSettings.id == 1)
    )
    bot_settings = result2.scalar_one_or_none()
    if bot_settings:
        urgent_price = float(bot_settings.urgent_price or 0)

    await query.message.edit_text(
        f"⚡ <b>Нужна срочность?</b>\n\n"
        f"За срочность доплачивается: <b>{urgent_price:.0f} ₽</b>\n\n"
        "Это позволяет мастеру выделить время именно для тебя 🙌",
        reply_markup=get_urgent_keyboard(urgent_price),
    )
    await query.answer()


# ─── Step 6: Urgent ─────────────────────────────────────────────────────────


async def handle_urgent_select(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Выбор срочности."""
    urgent = query.data.split(":", 1)[1] == "yes"
    data = await state.get_data()
    request_id = data.get("request_id")

    if request_id:
        stmt = select(TattooRequest).where(TattooRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.is_urgent = urgent
            if urgent:
                result3 = await session.execute(
                    select(BotSettings).where(BotSettings.id == 1)
                )
                bs = result3.scalar_one_or_none()
                if bs:
                    req.urgent_surcharge = float(bs.urgent_price or 0)
            await session.flush()

    await state.update_data(is_urgent=urgent)
    await state.set_state(RequestStates.collecting_brief_choice)
    await query.message.edit_text(
        "💡 <b>Хочешь заполнить анкету?</b>\n\n"
        "Поможет мастеру точнее понять твою идею.\n\n"
        "4 простых вопроса. Займёт минуту ⏱\n\n"
        "Если пропустишь — ничего страшного!",
        reply_markup=get_brief_choice_keyboard(),
    )
    await query.answer()


# ─── Step 7: Brief Choice ───────────────────────────────────────────────────


async def handle_brief_choice(
    query: CallbackQuery,
    state: FSMContext,
):
    """Выбор брифа."""
    choice = query.data.split(":", 1)[1]

    if choice == "skip":
        await state.set_state(RequestStates.reviewing)
        await _show_review_card(query.message, state)
        await query.answer()
    else:
        # Начинаем бриф с первого вопроса
        await state.set_state(RequestStates.brief_experienced)
        await query.message.edit_text(
            "🖊 <b>У тебя был опыт тату?</b>\n\n"
            "Это поможет мастеру понять, какой подход к тебе применить.",
            reply_markup=get_exp_keyboard(),
        )
        await query.answer()


# ─── Step 8: Brief Q1-Q4 ─────────────────────────────────────────────────────


async def handle_brief_experience(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Бриф Q1: опыт тату."""
    answer = query.data.split(":", 1)[1]
    data = await state.get_data()
    request_id = data.get("request_id")

    await state.update_data(brief_experience=answer)
    # Сохраняем в БД
    if request_id:
        bq = BriefQuestion(
            request_id=request_id,
            question_key="experience_level",
            answer_text=answer,
        )
        session.add(bq)
        await session.flush()

    await state.set_state(RequestStates.brief_style)
    await query.message.edit_text(
        "🎭 <b>Какой стиль тебе ближе?</b>",
        reply_markup=get_style_keyboard(),
    )
    await query.answer()


async def handle_brief_style(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Бриф Q2: стиль тату."""
    answer = query.data.split(":", 1)[1]
    data = await state.get_data()
    request_id = data.get("request_id")

    await state.update_data(brief_style=answer)
    if request_id:
        bq = BriefQuestion(
            request_id=request_id,
            question_key="preferred_style",
            answer_text=answer,
        )
        session.add(bq)
        await session.flush()

    await state.set_state(RequestStates.brief_inspiration)
    await query.message.edit_text(
        "💫 <b>Откуда ты берёшь вдохновение?</b>",
        reply_markup=get_inspiration_keyboard(),
    )
    await query.answer()


async def handle_brief_inspiration(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Бриф Q3: вдохновение."""
    answer = query.data.split(":", 1)[1]
    data = await state.get_data()
    request_id = data.get("request_id")

    await state.update_data(brief_inspiration=answer)
    if request_id:
        bq = BriefQuestion(
            request_id=request_id,
            question_key="inspiration_source",
            answer_text=answer,
        )
        session.add(bq)
        await session.flush()

    await state.set_state(RequestStates.brief_important)
    await query.message.edit_text(
        "✨ <b>Что для тебя важнее всего в тату?</b>",
        reply_markup=get_important_keyboard(),
    )
    await query.answer()


async def handle_brief_important(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Бриф Q4: что важнее."""
    answer = query.data.split(":", 1)[1]
    data = await state.get_data()
    request_id = data.get("request_id")

    await state.update_data(brief_important=answer)
    if request_id:
        bq = BriefQuestion(
            request_id=request_id,
            question_key="most_important",
            answer_text=answer,
        )
        session.add(bq)
        await session.flush()

    # Собираем все ответы брифа в JSONB
    brief_data = {
        "experience_level": data.get("brief_experience"),
        "preferred_style": data.get("brief_style"),
        "inspiration_source": data.get("brief_inspiration"),
        "most_important": data.get("brief_important"),
    }
    await state.update_data(brief_answers=brief_data)

    if request_id:
        stmt = select(TattooRequest).where(TattooRequest.id == request_id)
        result = await session.execute(stmt)
        req = result.scalar_one_or_none()
        if req:
            req.brief_answers = brief_data
            await session.flush()

    await state.set_state(RequestStates.reviewing)
    await _show_review_card(query.message, state)
    await query.answer()


# ─── Step 9: Review (FIXED: query.message instead of message) ────────────────


async def _show_review_card(message, state: FSMContext):
    """Показывает карточку финальной проверки."""
    data = await state.get_data()
    request_id = data.get("request_id", "?")

    color_text = "Ч/Б" if data.get("color_mode") == "bw" else "Цветная"
    urgent_text = "Да" if data.get("is_urgent") else "Нет"

    text = (
        f"📋 <b>Проверь заявку</b>\n\n"
        f"💬 {data.get('description', '')}\n\n"
        f"📍 Место: {data.get('location', '?')}\n"
        f"📏 Размер: {data.get('size', '?')}\n"
        f"🎨 Цвет: {color_text}\n"
        f"⚡ Срочность: {urgent_text}\n\n"
        f"📸 Референсы: будут добавлены после фото"
    )

    await message.answer(
        text,
        reply_markup=get_request_review_keyboard(request_id),
    )


# ─── Finalize ────────────────────────────────────────────────────────────────


async def handle_request_finalize(
    query: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
):
    """Финализация заявки (черновик → new). P0-1."""
    data = await state.get_data()
    request_id = data.get("request_id")

    if not request_id:
        await query.answer("Ошибка: данные заявки не найдены")
        return

    try:
        # P0-1: Меняем статус на 'new'
        result = await session.execute(
            select(TattooRequest).where(TattooRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if req:
            req.status = "new"
            await session.flush()

        await state.clear()
        await query.message.edit_text(
            f"🎉 Заявка #{request_id} отправлена!\n\n"
            f"Мастер Ариадна скоро посмотрит и ответит тебе.\n\n"
            f"Обычно это занимает несколько часов ✨",
        )
        await query.answer("Заявка отправлена! ✅")

    except Exception as e:
        await query.answer("❌ Ошибка при отправке. Попробуй ещё раз.")
        raise


# ─── Back navigation ─────────────────────────────────────────────────────────


async def handle_back(
    query: CallbackQuery,
    state: FSMContext,
):
    """Навигация назад."""
    current_state = await state.get_state()

    state_flows = [
        (RequestStates.collecting_references, RequestStates.collecting_description),
        (RequestStates.collecting_location, RequestStates.collecting_references),
        (RequestStates.collecting_size, RequestStates.collecting_location),
        (RequestStates.collecting_color, RequestStates.collecting_size),
        (RequestStates.collecting_urgent, RequestStates.collecting_color),
        (RequestStates.collecting_brief_choice, RequestStates.collecting_urgent),
        (RequestStates.reviewing, RequestStates.collecting_brief_choice),
    ]

    prev_state = None
    for current, prev in state_flows:
        if current == current_state:
            prev_state = prev
            break

    if prev_state:
        await state.set_state(prev_state)
        await query.message.answer(
            "← Возвращаюсь на предыдущий шаг",
            reply_markup=get_back_keyboard(),
        )
    else:
        await state.clear()
        await query.message.answer(
            "🗑 Создание заявки отменено.",
            reply_markup=get_main_keyboard(),
        )

    await query.answer()


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _get_or_create_draft(
    session: AsyncSession,
    user_id: int,
) -> int:
    """
    Получает или создаёт черновик для пользователя.
    P0-1: Черновик создаётся с status='draft' сразу.
    """
    result = await session.execute(
        select(TattooRequest)
        .where(
            TattooRequest.user_id == user_id,
            TattooRequest.status == "draft",
        )
        .order_by(TattooRequest.created_at.desc())
        .limit(1)
    )
    req = result.scalar_one_or_none()

    if req:
        return req.id

    # Создаём новый черновик
    new_req = TattooRequest(
        user_id=user_id,
        created_by=user_id,
        status="draft",
        description="",
        location="",
        size="",
        color_mode="bw",
        is_urgent=False,
    )
    session.add(new_req)
    await session.flush()
    return new_req.id
