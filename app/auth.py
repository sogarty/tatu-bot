"""Telegram WebApp Auth — валидация initData и зависимости авторизации.

Авторизация через Telegram WebApp initData:
- Клиент отправляет Authorization: TelegramWebApp <init_data_string>
- Сервер валидирует HMAC-SHA256 подпись с bot_token
- Извлекает user_id и определяет isAdmin через MASTER_TG_ID
"""

from __future__ import annotations

import hmac
import hashlib
import json
import time
from typing import Any

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.database import get_db
from app.dependencies import RequestNotFoundError
from app.models import TattooRequest


# ─── Валидация Telegram WebApp initData ─────────────────────────────────────


def verify_telegram_webapp_init_data(
    bot_token: str,
    init_data: str,
    ttl: int = 86400,  # 24 часа по умолчанию
) -> dict[str, Any] | None:
    """
    Валидирует Telegram WebApp initData.

    Проверяет:
    1. наличие hash в initData
    2. криптографическую подпись HMAC-SHA256 (WebAppData)
    3. срок действия (auth_date не истёк)

    Возвращает dict с 'user_id', 'user' при успехе, None при ошибке.
    """
    if not init_data or not bot_token:
        return None

    try:
        # Разбираем query string, извлекаем hash
        raw_params: dict[str, str] = {}
        for part in init_data.split("&"):
            eq_idx = part.find("=")
            if eq_idx > 0:
                key = part[:eq_idx]
                value = part[eq_idx + 1:]
                raw_params[key] = value

        hash_value = raw_params.pop("hash", "")
        if not hash_value:
            return None

        # Сортируем параметры по ключам и строим строку для проверки
        sorted_params = sorted(raw_params.items(), key=lambda x: x[0])
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted_params
        )

        # Вычисляем HMAC-SHA256: secret = hmac(key=bot_token, msg="WebAppData", algo=sha256).digest()
        # Затем: hmac(secret, data_check_string, sha256).hexdigest()
        # Согласно документации Telegram:
        # secret_key = HMAC-SHA256(bot_token, "WebAppData")
        # hash = HMAC-SHA256(secret_key, data_check_string)
        secret_key = hmac.new(
            bot_token.encode("utf-8"),
            b"WebAppData",
            hashlib.sha256,
        ).digest()

        computed_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        # Проверяем подпись (constant-time comparison)
        if not hmac.compare_digest(computed_hash, hash_value):
            return None

        # Проверяем TTL
        auth_date_str = raw_params.get("auth_date", "0")
        try:
            auth_date = int(auth_date_str)
        except ValueError:
            return None

        if time.time() - auth_date > ttl:
            return None

        # Извлекаем user
        user_json = raw_params.get("user", "{}")
        try:
            user_data = json.loads(user_json)
        except json.JSONDecodeError:
            return None

        user_id = user_data.get("id")
        if not user_id:
            return None

        return {
            "user_id": user_id,
            "user": user_data,
        }

    except Exception:
        return None


# ─── FastAPI зависимости ────────────────────────────────────────────────────


async def get_current_user(
    authorization: str | None = Header(None),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """
    Извлекает и валидирует данные пользователя из Authorization header.

    Формат: "Authorization: TelegramWebApp <init_data_string>"

    Возвращает: {"user_id": int, "is_admin": bool}
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header отсутствует",
        )

    prefix = "TelegramWebApp "
    if not authorization.startswith(prefix):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный формат Authorization header",
        )

    init_data = authorization[len(prefix):]

    verified = verify_telegram_webapp_init_data(
        bot_token=settings.bot_token,
        init_data=init_data,
    )

    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительные данные авторизации",
        )

    user_id: int = verified["user_id"]
    master_id: int = settings.master_tg_id
    is_admin: bool = (master_id > 0 and user_id == master_id)

    return {
        "user_id": user_id,
        "is_admin": is_admin,
    }


async def admin_only(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Защищает эндпоинт — требует администратора.

    Admin определяется через MASTER_TG_ID из настроек.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администратору",
        )
    return current_user


async def owner_of_request(
    request_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> TattooRequest:
    """
    Проверяет, что пользователь является владельцем заявки.
    Администратор может получить любую заявку.

    Возвращает TattooRequest или вызывает RequestNotFoundError (404).
    """
    stmt = select(TattooRequest).where(TattooRequest.id == request_id)
    result = await session.execute(stmt)
    req = result.scalar_one_or_none()

    if not req:
        raise RequestNotFoundError()

    # Админ видит любые заявки
    if current_user.get("is_admin"):
        return req

    # Обычный пользователь — только свои
    if req.user_id == current_user["user_id"]:
        return req

    # Чужая заявка — 404 (не 403, для безопасности)
    raise RequestNotFoundError()
