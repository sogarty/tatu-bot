"""Вспомогательные функции для бота."""

from __future__ import annotations

from datetime import date, datetime


def format_user_name(first_name: str, last_name: str | None, username: str | None) -> str:
    """Формирует имя пользователя для отображения.
    
    P0-5: Fallback для username.
    Если username есть → "@username ({first_name})"
    Иначе → "{first_name} {last_name or ''}"
    """
    if username:
        return f"@{username} ({first_name})"
    else:
        parts = [first_name]
        if last_name:
            parts.append(last_name)
        return " ".join(parts)


def format_date(date_obj: date | datetime) -> str:
    """Форматирует дату в формат DD.MM.YYYY."""
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    return date_obj.strftime("%d.%m.%Y")


def format_datetime(dt: datetime) -> str:
    """Форматирует дату и время в формат DD.MM.YYYY HH:MM."""
    return dt.strftime("%d.%m.%Y %H:%M")


def format_status_text(status: str) -> str:
    """Возвращает человеко-читаемый текст статуса заявки."""
    status_map = {
        "draft": "Черновик",
        "new": "В очереди",
        "accepted": "Принята",
        "in_progress": "Создаётся эскиз",
        "scheduled": "Записана",
        "completed": "Завершена",
        "rejected": "Отклонена",
        "cancelled": "Отменена",
    }
    return status_map.get(status, status)


def format_color_mode(mode: str) -> str:
    """Форматирует режим цвета."""
    return "Чёрно-белая" if mode == "bw" else "Цветная"


def format_urgent(is_urgent: bool) -> str:
    """Форматирует статус срочности."""
    return "Да" if is_urgent else "Нет"


def truncate_text(text: str, max_length: int = 100) -> str:
    """Обрезает текст до максимальной длины, добавляя '...' если нужно."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def paginate_list(items: list, page: int, per_page: int) -> tuple[list, int]:
    """Возвращает страницу элементов и общее количество страниц."""
    total_pages = (len(items) + per_page - 1) // per_page if items else 0
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total_pages


def format_queue_info(queue_rank: int | None, queue_order: int | None) -> str:
    """Форматирует информацию об очереди."""
    if queue_rank is None:
        return "Не в очереди"
    return f"#{queue_rank} в очереди"


def days_between(d1: date, d2: date) -> int:
    """Возвращает количество дней между двумя датами."""
    return (d2 - d1).days
