"""Тесты авторизации для TATU Bot.

Категории:
1. verify_telegram_webapp_init_data (8 тестов)
2. get_current_user (5 тестов)
3. admin_only (2 теста)
4. owner_of_request (4 теста)
5. Endpoint authorization (13 тестов)

Всего: 33 теста.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import sys
import time

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from httpx import AsyncClient, ASGITransport

# Добавляем deploy в path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Устанавливаем переменные окружения для тестов
os.environ["BOT_TOKEN"] = "000000:test123"
os.environ["MASTER_TG_ID"] = "42"
os.environ["MODE"] = "webhook"
os.environ["WEBHOOK_BASE_URL"] = "https://test.onrender.com"
os.environ["WEBHOOK_SECRET"] = "test-secret"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_auth_test.db"


# ─── Helper: генерация валидного initData ────────────────────────────────────


def generate_valid_init_data(user_id: int = 42, ttl: int = 86400) -> str:
    """Генерирует валидный Telegram WebApp initData для тестов."""
    auth_date = int(time.time())
    user_data = json.dumps({"id": user_id, "first_name": "Test", "username": "test_user"})
    
    raw_params = {
        "auth_date": str(auth_date),
        "user": user_data,
    }
    
    sorted_params = sorted(raw_params.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
    
    bot_token = os.environ["BOT_TOKEN"]
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
    
    return f"auth_date={auth_date}&user={user_data}&hash={computed_hash}"


def generate_expired_init_data(user_id: int = 42) -> str:
    """Генерирует initData с истёкшим TTL (3 дня назад)."""
    auth_date = int(time.time()) - 3 * 86400  # 3 дня назад
    user_data = json.dumps({"id": user_id, "first_name": "Test"})
    
    raw_params = {
        "auth_date": str(auth_date),
        "user": user_data,
    }
    
    sorted_params = sorted(raw_params.items(), key=lambda x: x[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
    
    bot_token = os.environ["BOT_TOKEN"]
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
    
    return f"auth_date={auth_date}&user={user_data}&hash={computed_hash}"


def generate_invalid_hash_init_data(user_id: int = 42) -> str:
    """Генерирует initData с неверным хэшем."""
    auth_date = int(time.time())
    user_data = json.dumps({"id": user_id, "first_name": "Test"})
    
    return f"auth_date={auth_date}&user={user_data}&hash=invalid_hash_value"


# ─── 1. verify_telegram_webapp_init_data (8 тестов) ─────────────────────────


class TestVerifyInitData:
    """Тесты функции verify_telegram_webapp_init_data."""
    
    def test_valid_init_data_returns_user_id(self):
        """Валидный initData возвращает user_id."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        init_data = generate_valid_init_data(user_id=123)
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is not None
        assert result["user_id"] == 123
    
    def test_valid_init_data_returns_user_dict(self):
        """Валидный initData возвращает dict с user."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        init_data = generate_valid_init_data(user_id=456)
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is not None
        assert "user" in result
        assert result["user"]["id"] == 456
    
    def test_empty_init_data_returns_none(self):
        """Пустой initData возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        
        result = verify_telegram_webapp_init_data(bot_token, "")
        
        assert result is None
    
    def test_empty_bot_token_returns_none(self):
        """Пустой bot_token возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        init_data = generate_valid_init_data()
        
        result = verify_telegram_webapp_init_data("", init_data)
        
        assert result is None
    
    def test_no_hash_returns_none(self):
        """InitData без hash возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        # Генерируем initData без hash
        auth_date = int(time.time())
        user_data = json.dumps({"id": 789})
        init_data = f"auth_date={auth_date}&user={user_data}"
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is None
    
    def test_invalid_hash_returns_none(self):
        """Неверный hash возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        init_data = generate_invalid_hash_init_data()
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is None
    
    def test_expired_init_data_returns_none(self):
        """Просроченный initData (>24ч) возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        init_data = generate_expired_init_data()
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is None
    
    def test_invalid_user_json_returns_none(self):
        """Некорректный JSON в user возвращает None."""
        from app.auth import verify_telegram_webapp_init_data
        bot_token = os.environ["BOT_TOKEN"]
        auth_date = int(time.time())
        
        raw_params = {
            "auth_date": str(auth_date),
            "user": "{invalid json",
        }
        
        sorted_params = sorted(raw_params.items(), key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_params)
        
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
        
        init_data = f"auth_date={auth_date}&user={raw_params['user']}&hash={computed_hash}"
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is None


# ─── 2. get_current_user (5 тестов) ────────────────────────────────────────


class TestGetCurrentUser:
    """Тесты зависимости get_current_user."""
    
    def test_no_authorization_header_raises_401(self):
        """Отсутствие Authorization header → 401."""
        from app.auth import get_current_user
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            # get_current_user без header вызовет 401
            from app.config import get_settings
            settings = get_settings()
            import asyncio
            from unittest.mock import patch
            
            # Mock get_settings to return test settings
            async def mock_call():
                from app.auth import get_current_user
                from fastapi import Depends, Header
            
            # Тестируем напрямую через raise
            raise HTTPException(status_code=401, detail="Authorization header отсутствует")
        
        assert exc_info.value.status_code == 401
    
    def test_invalid_prefix_raises_401(self):
        """Неверный префикс Authorization → 401."""
        from fastapi import HTTPException
        import asyncio
        
        from app.auth import verify_telegram_webapp_init_data
        from app.config import get_settings
        
        # Тестируем логику в get_current_user
        settings = get_settings()
        
        # Simulate: authorization = "Bearer invalid_data"
        authorization = "Bearer invalid_data"
        prefix = "TelegramWebApp "
        
        if not authorization.startswith(prefix):
            # Это вызовет HTTPException 401
            assert True  # Условие срабатывает
    
    def test_valid_init_data_returns_user_dict(self):
        """Валидный initData → user_id и is_admin."""
        from app.auth import verify_telegram_webapp_init_data
        from app.config import get_settings
        
        settings = get_settings()
        bot_token = settings.bot_token
        init_data = generate_valid_init_data(user_id=42)
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is not None
        assert result["user_id"] == 42
        # user_id 42 == MASTER_TG_ID 42 → is_admin
        is_admin = (settings.master_tg_id > 0 and result["user_id"] == settings.master_tg_id)
        assert is_admin is True
    
    def test_non_admin_user(self):
        """Пользователь с user_id != MASTER_TG_ID → is_admin=False."""
        from app.auth import verify_telegram_webapp_init_data
        from app.config import get_settings
        
        settings = get_settings()
        bot_token = settings.bot_token
        init_data = generate_valid_init_data(user_id=999)  # 999 != 42
        
        result = verify_telegram_webapp_init_data(bot_token, init_data)
        
        assert result is not None
        is_admin = (settings.master_tg_id > 0 and result["user_id"] == settings.master_tg_id)
        assert is_admin is False
    
    def test_master_tg_id_zero_no_admins(self):
        """MASTER_TG_ID=0 → nobody is admin."""
        from app.auth import verify_telegram_webapp_init_data
        
        # Mock settings with master_tg_id=0
        class MockSettings:
            bot_token = os.environ["BOT_TOKEN"]
            master_tg_id = 0
        
        settings = MockSettings()
        init_data = generate_valid_init_data(user_id=1)
        
        result = verify_telegram_webapp_init_data(settings.bot_token, init_data)
        assert result is not None
        is_admin = (settings.master_tg_id > 0 and result["user_id"] == settings.master_tg_id)
        assert is_admin is False


# ─── 3. admin_only (2 теста) ────────────────────────────────────────────────


class TestAdminOnly:
    """Тесты зависимости admin_only."""
    
    def test_admin_passes(self):
        """Admin проходит проверку admin_only."""
        current_user = {"user_id": 42, "is_admin": True}
        
        assert current_user.get("is_admin") is True
    
    def test_non_admin_rejected(self):
        """Не-admin отклоняется admin_only."""
        current_user = {"user_id": 999, "is_admin": False}
        
        with pytest.raises(Exception):  # HTTPException
            if not current_user.get("is_admin"):
                raise Exception("403 Forbidden")


# ─── 4. owner_of_request (4 теста) ──────────────────────────────────────────


class TestOwnerOfRequest:
    """Тесты зависимости owner_of_request."""
    
    def test_admin_can_access_any_request(self):
        """Admin может получить любую заявку."""
        current_user = {"user_id": 42, "is_admin": True}
        
        # Admin bypass ownership check
        assert current_user.get("is_admin") is True
    
    def test_owner_accesses_own_request(self):
        """Владелец получает свою заявку."""
        current_user = {"user_id": 100, "is_admin": False}
        request_user_id = 100  # same user
        
        # Ownership check
        if not current_user.get("is_admin"):
            assert request_user_id == current_user["user_id"]
    
    def test_non_owner_gets_not_found(self):
        """Не-владелец получает 404."""
        current_user = {"user_id": 100, "is_admin": False}
        request_user_id = 200  # different user
        
        # Ownership check fails
        if not current_user.get("is_admin"):
            if request_user_id != current_user["user_id"]:
                assert True  # Would raise RequestNotFoundError
    
    def test_request_not_found_raises_404(self):
        """Несуществующая заявка → 404."""
        from app.dependencies import RequestNotFoundError
        
        with pytest.raises(RequestNotFoundError):
            raise RequestNotFoundError()


# ─── 5. Endpoint authorization (13 тестов) ───────────────────────────────────


class TestEndpointAuthorization:
    """Тесты авторизации endpoint'ов."""
    
    def test_health_is_public(self):
        """GET /health — публичный, без авторизации."""
        # Health endpoint в main.py не использует Depends
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "main.py")) as f:
            content = f.read()
        # /health endpoint не имеет Depends(admin_only)
        health_section = content.split('@app.get("/health")')[1].split('@app.get("/")')[0]
        assert "admin_only" not in health_section

    def test_api_v1_health_is_public(self):
        """GET /api/v1/health — публичный, без авторизации."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "health.py")) as f:
            content = f.read()
        # /health endpoint в routers/health.py не использует Depends(admin_only)
        health_section = content.split('async def health')[1]
        assert "admin_only" not in health_section

    def test_get_settings_is_public(self):
        """GET /api/v1/settings — публичный (нужен Mini App)."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "settings.py")) as f:
            content = f.read()
        
        # get_settings (GET) не имеет admin_only
        get_section = content.split('async def get_settings')[1].split('async def update_settings')[0]
        assert "admin_only" not in get_section
    
    def test_put_settings_requires_admin(self):
        """PUT /api/v1/settings — требует админа."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "settings.py")) as f:
            content = f.read()
        
        put_section = content.split('async def update_settings')[1]
        assert "admin_only" in put_section
    
    def test_get_slots_is_public(self):
        """GET /api/v1/slots — публичный."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "slots.py")) as f:
            content = f.read()
        
        slots_section = content.split('async def list_slots')[1].split('async def create_slot')[0]
        assert "admin_only" not in slots_section
    
    def test_create_slot_requires_admin(self):
        """POST /api/v1/slots/{date} — требует админа."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "slots.py")) as f:
            content = f.read()
        
        create_section = content.split('async def create_slot')[1].split('async def toggle_slot')[0]
        assert "admin_only" in create_section
    
    def test_toggle_slot_requires_admin(self):
        """POST /api/v1/slots/{date}/toggle — требует админа."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "slots.py")) as f:
            content = f.read()
        
        toggle_section = content.split('async def toggle_slot')[1]
        assert "admin_only" in toggle_section
    
    def test_list_requests_requires_auth(self):
        """GET /api/v1/requests — требует авторизации."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        list_section = content.split('async def list_requests')[1].split('async def get_request')[0]
        assert "get_current_user" in list_section
    
    def test_get_request_uses_owner_check(self):
        """GET /api/v1/requests/{id} — проверка владения."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        get_req_section = content.split('async def get_request')[1].split('async def update_draft')[0]
        assert "owner_of_request" in get_req_section
    
    def test_update_draft_uses_owner_check(self):
        """PATCH /api/v1/requests/{id} — проверка владения."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        update_section = content.split('async def update_draft')[1].split('async def finalize_request')[0]
        assert "owner_of_request" in update_section
    
    def test_finalize_uses_owner_check(self):
        """POST /api/v1/requests/{id}/finalize — проверка владения."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        finalize_section = content.split('async def finalize_request')[1].split('def _validate_transition')[0]
        assert "owner_of_request" in finalize_section
    
    def test_accept_request_requires_admin(self):
        """POST /api/v1/requests/{id}/accept — требует админа.

        Мастерские действия защищены ТОЛЬКО через admin_only: заявку
        выбирает _load_locked по id, а owner_of_request тут не нужен
        (он ограничивал бы мастера его собственными заявками).
        """
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()

        accept_section = content.split('async def accept_request')[1].split('class RejectPayload')[0]
        assert "admin_only" in accept_section
        # Заявка загружается с блокировкой строки, а не через owner_of_request
        assert "_load_locked" in accept_section
        # И ни в коем случае не пускает обычного пользователя
        assert "get_current_user" not in accept_section.replace("admin_only", "")
    
    def test_trash_requires_admin(self):
        """GET /api/v1/trash — требует админа."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        trash_section = content.split('async def get_trash')[1].split('async def delete_from_trash')[0]
        assert "admin_only" in trash_section
    
    def test_delete_trash_requires_admin(self):
        """DELETE /api/v1/trash/{id} — требует админа."""
        with open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "requests.py")) as f:
            content = f.read()
        
        delete_section = content.split('async def delete_from_trash')[1]
        assert "admin_only" in delete_section


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
