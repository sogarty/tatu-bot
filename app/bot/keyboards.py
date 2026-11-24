"""Inline keyboard builders для бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню клиента."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✍️ Хочу тату"),
                KeyboardButton(text="📋 Мои заявки"),
            ],
            [
                KeyboardButton(text="📅 Календарь"),
                KeyboardButton(text="💬 Написать мастеру"),
            ],
        ],
        resize_keyboard=True,
    )


def get_request_review_keyboard(request_id: int) -> InlineKeyboardMarkup:
    """Финальная проверка заявки — кнопки 'Отправить' / 'Изменить'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Отправить заявку",
                    callback_data=f"request_finalized:{request_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=f"request_edit:{request_id}",
                ),
            ],
        ]
    )


def get_color_keyboard() -> InlineKeyboardMarkup:
    """Кнопки выбора цвета (ШАГ 5)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◼️ Чёрно-белая",
                    callback_data="color:bw",
                ),
                InlineKeyboardButton(
                    text="◻️ Цветная",
                    callback_data="color:color",
                ),
            ],
        ]
    )


def get_urgent_keyboard(urgent_price: float) -> InlineKeyboardMarkup:
    """Кнопки выбора срочности (ШАГ 6)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⚡ Да, срочно (+{urgent_price:.0f}₽)",
                    callback_data="urgent:yes",
                ),
                InlineKeyboardButton(
                    text="○ Нет, обычная",
                    callback_data="urgent:no",
                ),
            ],
        ]
    )


def get_brief_choice_keyboard() -> InlineKeyboardMarkup:
    """Выбор брифа (ШАГ 7)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Заполнить анкету",
                    callback_data="brief:fill",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ Пропустить",
                    callback_data="brief:skip",
                ),
            ],
        ]
    )


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка 'Назад'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data="back",
                ),
            ],
        ]
    )


# ─── Admin keyboards ────────────────────────────────────────────────────────


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню администратора."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Заявки",
                    callback_data="admin:requests",
                ),
                InlineKeyboardButton(
                    text="📅 Календарь",
                    callback_data="admin:calendar",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗑 Корзина",
                    callback_data="admin:trash",
                ),
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="admin:settings",
                ),
            ],
        ]
    )


def get_request_actions_keyboard(request_id: int, status: str) -> InlineKeyboardMarkup:
    """Кнопки действий для заявки (зависят от статуса)."""
    buttons = []

    if status == "new":
        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Принять",
                    callback_data=f"req_accept:{request_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"req_reject:{request_id}",
                ),
            ]
        ]

    elif status == "accepted":
        buttons = [
            [
                InlineKeyboardButton(
                    text="🖌 Берусь за эскиз",
                    callback_data=f"req_proceed:{request_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"req_reject:{request_id}",
                ),
                InlineKeyboardButton(
                    text="↩️ Вернуть в new",
                    callback_data=f"req_return_new:{request_id}",
                ),
            ],
        ]

    elif status == "in_progress":
        buttons = [
            [
                InlineKeyboardButton(
                    text="📅 Назначить дату",
                    callback_data=f"req_schedule:{request_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"req_reject:{request_id}",
                ),
                InlineKeyboardButton(
                    text="↩️ Вернуть в accepted",
                    callback_data=f"req_return_accepted:{request_id}",
                ),
            ],
        ]

    elif status == "scheduled":
        buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Сеанс проведён",
                    callback_data=f"req_complete:{request_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отменить запись",
                    callback_data=f"req_cancel:{request_id}",
                ),
            ],
        ]

    elif status == "rejected":
        buttons = [
            [
                InlineKeyboardButton(
                    text="↩️ Возобновить",
                    callback_data=f"req_reactivate:{request_id}",
                ),
            ],
        ]

    buttons.append([
        InlineKeyboardButton(
            text="← Назад к списку",
            callback_data="admin:requests",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_calendar_keyboard(
    year: int, month: int, booked_dates: list[str], current_date: str
) -> InlineKeyboardMarkup:
    """Inline-календарь для выбора даты."""
    import calendar
    from datetime import date

    buttons = []

    # Навигация по месяцам
    buttons.append([
        InlineKeyboardButton(
            text="◀",
            callback_data=f"cal_prev:{year}:{month}",
        ),
        InlineKeyboardButton(
            text=f"{calendar.month_name[month]} {year}",
            callback_data="cal_nop",
        ),
        InlineKeyboardButton(
            text="▶",
            callback_data=f"cal_next:{year}:{month}",
        ),
    ])

    # Дни недели
    buttons.append([
        InlineKeyboardButton(text="Пн", callback_data="cal_nop"),
        InlineKeyboardButton(text="Вт", callback_data="cal_nop"),
        InlineKeyboardButton(text="Ср", callback_data="cal_nop"),
        InlineKeyboardButton(text="Чт", callback_data="cal_nop"),
        InlineKeyboardButton(text="Пт", callback_data="cal_nop"),
        InlineKeyboardButton(text="Сб", callback_data="cal_nop"),
        InlineKeyboardButton(text="Вс", callback_data="cal_nop"),
    ])

    # Дни месяца
    cal = calendar.Calendar(firstweekday=calendar.MONDAY)
    month_days = cal.monthdayscalendar(year, month)

    for week in month_days:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="cal_nop"))
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                is_booked = date_str in booked_dates
                is_today = date_str == current_date

                if is_today:
                    text = f"◼{day}"
                elif is_booked:
                    text = f"✕{day}"
                else:
                    text = str(day)

                row.append(InlineKeyboardButton(
                    text=text,
                    callback_data=f"cal_select:{date_str}",
                ))
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(text="← Назад", callback_data="admin:calendar"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── Brief question keyboards ──────────────────────────────────────────────


def get_exp_keyboard() -> InlineKeyboardMarkup:
    """Кнопки для брифа Q1: опыт тату."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🆕 Нет, это будет первая",
                    callback_data="brief_exp:no",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖊 Была 1–2",
                    callback_data="brief_exp:1-2",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎨 Было 3+",
                    callback_data="brief_exp:3plus",
                ),
            ],
        ]
    )


def get_style_keyboard() -> InlineKeyboardMarkup:
    """Кнопки для брифа Q2: стиль тату."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Реализм", callback_data="brief_style:realism"),
                InlineKeyboardButton(text="✏️ Графика", callback_data="brief_style:graphics"),
            ],
            [
                InlineKeyboardButton(text="💧 Акварель", callback_data="brief_style:watercolor"),
                InlineKeyboardButton(text="🔷 Геометрия", callback_data="brief_style:geometry"),
            ],
        ]
    )


def get_inspiration_keyboard() -> InlineKeyboardMarkup:
    """Кнопки для брифа Q3: вдохновение."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📌 Pinterest", callback_data="brief_insp:pinterest"),
            ],
            [
                InlineKeyboardButton(text="📷 Instagram", callback_data="brief_insp:instagram"),
            ],
            [
                InlineKeyboardButton(text="🤷 Не знаю", callback_data="brief_insp:unknown"),
            ],
        ]
    )


def get_important_keyboard() -> InlineKeyboardMarkup:
    """Кнопки для брифа Q4: что важнее."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎨 Эстетика", callback_data="brief_important:aesthetics"),
            ],
            [
                InlineKeyboardButton(text="💭 Смысл / значение", callback_data="brief_important:meaning"),
            ],
            [
                InlineKeyboardButton(text="🛡 Безопасность", callback_data="brief_important:safety"),
            ],
        ]
    )


# ─── Callback Registration ──────────────────────────────────────────────────


def register_kb_callbacks(dp):
    """
    Регистрирует callback-обработчики для inline-кнопок.
    Этот хелпер можно расширять для обработки callback'ов.
    """
    # Пока пустой хелпер — все callback'и зарегистрированы в handlers
    pass
