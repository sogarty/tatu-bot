"""Telegram WebApp Auth — валидация initData и зависимости авторизации.

Авторизация через Telegram WebApp initData:
- Клиент отправляет Authorization: TelegramWebApp <init_data_string>
- Сервер валидирует HMAC-SHA256 подпись с bot_token
- Извлекает user_id и определяет isAdmin через MASTER_TG_ID

Алгоритм — из официальной документации Telegram
(https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):

    secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash       = HMAC_SHA256(key=secret_key,   msg=data_check_string)

где data_check_string — все поля, кроме hash, отсортированные по имени
в формате key=value и соединённые переводом строки.

ВАЖНО про порядок аргументов: ключ — литерал "WebAppData", данные — токен.
Перестановка местами даёт другую подпись, и тогда отвергается ЛЮБОЙ
настоящий вход из Telegram. Именно эта ошибка и была здесь раньше;
тесты её не ловили, потому что подписывали данные той же неверной
формулой. Теперь проверка сверяется с независимой реализацией aiogram
(см. scripts/verify_auth_signature.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.database import get_db
from app.dependencies import RequestNotFoundError
from app.models import Appointment, TattooRequest

# Сколько живёт initData. Telegram обновляет его при каждом открытии
# приложения, поэтому сутки — безопасный и достаточный срок.
DEFAULT_TTL_SECONDS = 86400
MAX_CLOCK_SKEW_SECONDS = 60


# ─── Валидация Telegram WebApp initData ─────────────────────────────────────


def _build_check_string(params: dict[str, str]) -> str:
    """Собирает data_check_string: key=value, по алфавиту, через \\n."""
    return "\n".join(f"{key}={params[key]}" for key in sorted(params))


def _hash_matches(bot_token: str, check_string: str, received_hash: str) -> bool:
    """Сверяет HMAC-SHA256 подпись в постоянном времени.

    secret_key = HMAC(key=b"WebAppData", msg=bot_token)
    hash       = HMAC(key=secret_key,      msg=data_check_string)

    Ключ и данные нельзя менять местами — это разные подписи.
    """
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    computed = hmac.new(
        secret_key,
        check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(
        computed.encode("utf-8"), received_hash.encode("utf-8")
    )


def verify_telegram_webapp_init_data(
    bot_token: str,
    init_data: str,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Валидирует Telegram WebApp initData.

    Проверяет:
    1. наличие hash в initData
    2. криптографическую подпись HMAC-SHA256
    3. срок действия (auth_date не истёк)

    Возвращает dict с 'user_id', 'user' при успехе, None при любой ошибке.
    """
    if not init_data or not bot_token:
        return None

    try:
        # parse_qsl сам раскодирует %XX и '+' — это критично: Telegram
        # присылает значения в URL-кодировке, и подпись считается по
        # раскодированным значениям.
        raw_params: dict[str, str] = dict(
            parse_qsl(init_data, keep_blank_values=True)
        )

        hash_value = raw_params.pop("hash", "")
        if not hash_value:
            return None

        # `signature` (Bot API 8.0+) — спорный случай: документация для
        # Ed25519-проверки исключает его из строки, а aiogram при проверке
        # hash включает. Поэтому пробуем оба варианта: без него и с ним.
        # Безопасность не страдает — в любом варианте нужна подпись,
        # невоспроизводимая без bot_token.
        params_for_hash = dict(raw_params)
        params_for_hash.pop("signature", None)

        check_string = _build_check_string(params_for_hash)
        ok = _hash_matches(bot_token, check_string, hash_value)

        if not ok and "signature" in raw_params:
            ok = _hash_matches(
                bot_token, _build_check_string(raw_params), hash_value
            )

        if not ok:
            return None

        # Проверяем TTL
        try:
            auth_date = int(raw_params.get("auth_date", "0"))
        except ValueError:
            return None

        if auth_date <= 0:
            return None
        now = time.time()
        if auth_date > now + MAX_CLOCK_SKEW_SECONDS:
            return None
        if now - auth_date > ttl:
            return None

        # Извлекаем user
        try:
            user_data = json.loads(raw_params.get("user", "{}"))
        except json.JSONDecodeError:
            return None

        if not isinstance(user_data, dict):
            return None

        user_id = user_data.get("id")
        if not isinstance(user_id, int) or user_id <= 0:
            return None

        return {
            "user_id": user_id,
            "user": user_data,
            "auth_date": auth_date,
        }

    except Exception:
        return None


# ─── FastAPI зависимости ────────────────────────────────────────────────────


async def get_current_user(
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Извлекает и валидирует пользователя из заголовка Authorization.

    Формат: "Authorization: TelegramWebApp <init_data_string>"

    Возвращает: {"user_id": int, "is_admin": bool, "user": dict}
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужно открыть приложение из Telegram",
        )

    prefix = "TelegramWebApp "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат заголовка авторизации",
        )

    init_data = authorization[len(prefix):].strip()

    verified = verify_telegram_webapp_init_data(
        bot_token=settings.bot_token,
        init_data=init_data,
    )

    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Данные Telegram недействительны или устарели",
        )

    user_id: int = verified["user_id"]
    master_id: int = settings.master_tg_id

    return {
        "user_id": user_id,
        "is_admin": bool(master_id > 0 and user_id == master_id),
        "user": verified.get("user", {}),
    }


async def admin_only(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Защищает эндпоинт — требует администратора."""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только мастеру",
        )
    return current_user


async def load_request_for_user(
    request_id: int,
    session: AsyncSession,
    current_user: dict[str, Any],
) -> TattooRequest:
    """Загружает заявку со всеми связями и проверяет права доступа.

    Связи (references / brief_questions / appointment) загружаются сразу:
    без этого сериализация ответа падала с MissingGreenlet.
    """
    from sqlalchemy.orm import selectinload

    stmt = (
        select(TattooRequest)
        .where(TattooRequest.id == request_id)
        .options(
            selectinload(TattooRequest.references),
            selectinload(TattooRequest.brief_questions),
            selectinload(TattooRequest.appointment).selectinload(Appointment.slot),
            selectinload(TattooRequest.user),
        )
    )
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()

    if not req:
        raise RequestNotFoundError()

    # Мастер видит любые заявки
    if current_user.get("is_admin"):
        return req

    # Обычный пользователь — только свои (404, чтобы не раскрывать чужие id)
    if req.user_id == current_user["user_id"] and not req.is_archived:
        return req

    raise RequestNotFoundError()


async def owner_of_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TattooRequest:
    """Зависимость: заявка, доступная текущему пользователю."""
    return await load_request_for_user(request_id, session, current_user)
