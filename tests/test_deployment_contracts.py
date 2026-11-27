"""Deployment contract tests for migrations and readiness reporting."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import asyncio
from types import SimpleNamespace

import pytest


def test_alembic_head_applies_idempotency_schema(tmp_path):
    """A clean database must reach the same migration head used in startup."""
    database = tmp_path / "migration.db"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": ".",
            "BOT_TOKEN": "test_token_for_migrations",
            "DATABASE_URL": f"sqlite+aiosqlite:///{database.as_posix()}",
            "ENVIRONMENT": "development",
            "MODE": "longpoll",
        }
    )
    script = (
        "from alembic.config import Config; "
        "from alembic import command; "
        "config = Config('alembic.ini'); "
        "config.set_main_option('script_location', 'alembic'); "
        "command.upgrade(config, '008')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    # Simulate a record created by the old API: published, but with no image.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO portfolio_item "
            "(title, place, image_url, image_data, image_content_type, tags, "
            "is_published, sort_order, created_at, updated_at) "
            "VALUES (?, ?, NULL, NULL, NULL, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("Старая работа без фото", "Рука", "[]", 100),
        )
        connection.commit()

    upgrade_script = (
        "from alembic.config import Config; "
        "from alembic import command; "
        "config = Config('alembic.ini'); "
        "config.set_main_option('script_location', 'alembic'); "
        "command.upgrade(config, 'head')"
    )
    result = subprocess.run(
        [sys.executable, "-c", upgrade_script],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("011",)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(tattoo_request)")
        }
        assert "idempotency_key" in columns
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(tattoo_request)")
        }
        assert "uq_tattoo_request_user_idempotency" in indexes
        reference_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(request_reference)")
        }
        assert {"image_data", "image_content_type", "has_uploaded_image"} <= (
            reference_columns
        )
        captions = dict(
            connection.execute(
                "SELECT image_url, title FROM portfolio_item WHERE image_url IN (?, ?)",
                ("assets/portfolio/k12.jpg", "assets/portfolio/k14.jpg"),
            )
        )
        assert captions == {
            "assets/portfolio/k12.jpg": "Крылья и хризантема",
            "assets/portfolio/k14.jpg": "Пятнистая кошка",
        }
        assert connection.execute(
            "SELECT categories FROM portfolio_item WHERE image_url = ?",
            ("assets/portfolio/k12.jpg",),
        ).fetchone() == ('["black"]',)
        assert connection.execute(
            "SELECT is_published FROM portfolio_item WHERE title = ?",
            ("Старая работа без фото",),
        ).fetchone() == (0,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO portfolio_item "
                "(title, place, image_url, image_data, image_content_type, tags, "
                "is_published, sort_order, created_at, updated_at) "
                "VALUES (?, ?, NULL, NULL, NULL, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                ("Запись без фото", "Рука", "[]", 101),
            )


def test_health_requires_webhook_readiness(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    import app.main as main_module
    import app.routers.health as health_module

    settings = SimpleNamespace(
        environment="production",
        allow_ephemeral_database=False,
        mode="webhook",
        master_tg_id=42,
    )
    monkeypatch.setattr(health_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "bot", object())
    monkeypatch.setattr(main_module, "webhook_ready", False)
    monkeypatch.setattr(main_module, "webhook_error", "Telegram unavailable")

    session = MagicMock()
    session.bind.url.get_backend_name.return_value = "postgresql"
    session.execute = AsyncMock()

    response = asyncio.run(health_module.health(session))
    assert response.status_code == 503
    assert json.loads(response.body)["webhook_ready"] is False

    monkeypatch.setattr(main_module, "webhook_ready", True)
    payload = asyncio.run(health_module.health(session))
    assert payload["status"] == "ok"
    assert payload["webhook_ready"] is True
