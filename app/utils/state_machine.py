"""Машин состояний для заявок. Определяет допустимые переходы статусов."""

from __future__ import annotations

# Карта: текущий_статус -> множество допустимых следующих статусов
TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"new"}),
    "new": frozenset({"accepted", "rejected"}),
    "accepted": frozenset({"in_progress", "rejected", "new"}),
    "in_progress": frozenset({"scheduled", "rejected", "accepted"}),
    # `scheduled -> new` is deliberately absent: cancellation must go through
    # the paired appointment operation in request_service.
    "scheduled": frozenset({"completed", "cancelled"}),
    "completed": frozenset(),
    "rejected": frozenset({"new"}),
    "cancelled": frozenset(),
}


ALLOWED_TRANSITIONS = TRANSITIONS


def is_valid_transition(current: str, target: str) -> bool:
    """Проверяет, допустим ли переход статуса."""
    allowed = TRANSITIONS.get(current, frozenset())
    return target in allowed


def get_allowed_transitions(current: str) -> list[str]:
    """Возвращает список допустимых следующих статусов."""
    return sorted(TRANSITIONS.get(current, frozenset()))


# Описание переходов для UI
TRANSITION_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "draft -> new": "Заявка отправлена клиентом",
    "new -> accepted": "Мастер принял заявку",
    "new -> rejected": "Мастер отклонил заявку",
    "accepted -> in_progress": "Мастер берётся за эскиз",
    "accepted -> rejected": "Мастер отклонил после принятия",
    "accepted -> new": "Заявка возвращена в начало",
    "in_progress -> scheduled": "Назначена дата сеанса",
    "in_progress -> rejected": "Мастер отклонил во время работы",
    "in_progress -> accepted": "Заявка возвращена в accepted",
    "scheduled -> completed": "Сеанс проведён",
    "scheduled -> cancelled": "Запись отменена",
    "rejected -> new": "Заявка возобновлена",
}


def get_transition_description(current: str, target: str) -> str:
    """Возвращает человеко-читаемое описание перехода."""
    key = f"{current} -> {target}"
    return TRANSITION_DESCRIPTIONS.get(key, f"Переход {current} → {target}")
