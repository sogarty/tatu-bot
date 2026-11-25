"""Проверка работоспособности (smoke-тест) — этап 1.

Запуск:
    python scripts/verify.py

Каждая строка PASS — проверенный факт, а не обещание. Если скрипт
упал или напечатал FAIL, значит система НЕ готова к деплою.

Скрипт работает на временной базе в системной папке temp и не трогает
рабочую базу проекта.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

# ── Настройки окружения ДО импорта приложения ────────────────────────────────
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_DB_FILE = pathlib.Path(tempfile.gettempdir()) / "tatu_verify.db"
if _DB_FILE.exists():
    _DB_FILE.unlink()

os.environ.setdefault("BOT_TOKEN", "123456789:VERIFY_ONLY_TOKEN")
os.environ.setdefault("MASTER_TG_ID", "42")
os.environ.setdefault("MODE", "webhook")
os.environ.setdefault("ENVIRONMENT", "production")
os.environ.setdefault("WEBHOOK_BASE_URL", "")
os.environ.setdefault("WEBHOOK_SECRET", "")
os.environ.setdefault("WEBAPP_URL", "https://example.test/app/")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_FILE}"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"{mark}  {name}" + (f"  — {detail}" if detail else ""))


# ── 1. База данных ───────────────────────────────────────────────────────────
async def check_db() -> None:
    from datetime import date

    from app.database import async_session_factory, init_db
    from app.models import Appointment, MasterSlot, TattooRequest, TgUser

    await init_db()

    # TgUser без указания id
    async with async_session_factory() as s:
        user = TgUser(tg_id=777, first_name="Анна")
        s.add(user)
        try:
            await s.commit()
            check("db: TgUser создаётся без id", user.id is not None, f"id={user.id}")
        except Exception as exc:
            check("db: TgUser создаётся без id", False, f"{type(exc).__name__}: {exc}")
            await s.rollback()

    # Заявка
    async with async_session_factory() as s:
        req = TattooRequest(
            user_id=777, created_by=777, description="идея " * 5,
            location="предплечье", size="10", color_mode="bw", status="new",
        )
        s.add(req)
        try:
            await s.commit()
            check("db: TattooRequest создаётся без id", req.id is not None, f"id={req.id}")
            request_id = req.id
        except Exception as exc:
            check("db: TattooRequest создаётся без id", False, f"{type(exc).__name__}: {exc}")
            await s.rollback()
            return

    # Слот
    async with async_session_factory() as s:
        slot = MasterSlot(slot_date=date(2026, 12, 1))
        s.add(slot)
        try:
            await s.commit()
            check("db: MasterSlot создаётся без id", slot.id is not None, f"id={slot.id}")
            slot_id = slot.id
        except Exception as exc:
            check("db: MasterSlot создаётся без id", False, f"{type(exc).__name__}: {exc}")
            await s.rollback()
            return

    # Запись (appointment)
    async with async_session_factory() as s:
        appt = Appointment(request_id=request_id, slot_id=slot_id)
        s.add(appt)
        try:
            await s.commit()
            check("db: Appointment создаётся без id", appt.id is not None, f"id={appt.id}")
        except Exception as exc:
            check("db: Appointment создаётся без id", False, f"{type(exc).__name__}: {exc}")
            await s.rollback()

    # Уникальность слота: вторая запись на тот же слот должна упасть
    async with async_session_factory() as s:
        dup = Appointment(request_id=request_id, slot_id=slot_id)
        s.add(dup)
        try:
            await s.commit()
            check("db: защита от двух записей на один день", False, "дубль прошёл!")
            await s.rollback()
        except Exception:
            await s.rollback()
            check("db: защита от двух записей на один день", True)


# ── 2. Веб: раздача Mini App ─────────────────────────────────────────────────
def check_web() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        r = client.get("/health")
        check("web: GET /health = 200", r.status_code == 200, r.text[:40])

        r = client.get("/app/")
        ok = r.status_code == 200 and "<html" in r.text.lower()
        check("web: GET /app/ отдаёт страницу приложения", ok,
              f"status={r.status_code}, {len(r.text)} байт")

        r = client.get("/api/v1/settings")
        check("web: GET /api/v1/settings = 200", r.status_code == 200)

        # Падающий update не должен ронять webhook
        r = client.post("/webhook", json={"update_id": 1, "message": {"message_id": 1}})
        check("web: битый update → webhook 200", r.status_code == 200, r.text[:40])

        # Невалидный JSON — единственный законный 400
        r = client.post("/webhook", content=b"{ broken",
                        headers={"Content-Type": "application/json"})
        check("web: битый JSON → webhook 400", r.status_code == 400)


# ── 3. Бот: /start ───────────────────────────────────────────────────────────
async def check_bot() -> None:
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.types import Update
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.main import _create_dp

    sent: list = []

    class DummySession(BaseSession):
        async def close(self):
            pass

        async def make_request(self, bot, method, timeout=None):
            sent.append(method)
            return True

        async def stream_content(self, *a, **k):
            yield b""

    def update(uid: int, text: str) -> Update:
        return Update.model_validate(
            {
                "update_id": uid,
                "message": {
                    "message_id": uid, "date": 1795500000,
                    "chat": {"id": 555, "type": "private"},
                    "from": {"id": 555, "is_bot": False,
                             "first_name": "Анна", "username": "anna"},
                    "text": text,
                },
            },
            context={"bot": bot},
        )

    dp = _create_dp()
    bot = Bot(token=os.environ["BOT_TOKEN"], session=DummySession())

    for i in (101, 102):
        try:
            await dp.feed_update(bot, update(i, "/start"))
        except Exception as exc:
            check(f"bot: /start #{i} не падает", False, f"{type(exc).__name__}: {exc}")
            return

    check("bot: /start отправляет 2 сообщения", len(sent) == 2, f"отправлено {len(sent)}")

    if sent:
        msg = sent[0]
        text = getattr(msg, "text", "") or ""
        kb = getattr(getattr(msg, "reply_markup", None), "inline_keyboard", None)
        check("bot: у приветствия есть кнопка приложения", bool(kb))
        check("bot: в приветствии нет «Арину»", "Арину" not in text)
        check("bot: в приветствии нет «Арин»", "Арин" not in text)

    # Один пользователь при двух /start
    async with async_session_factory() as s:
        n = (await s.execute(select(func.count()).select_from(
            __import__("app.models", fromlist=["TgUser"]).TgUser
        ))).scalar()
    # 777 из check_db + 555 от бота
    check("bot: два /start = один пользователь", n == 2, f"записей TgUser: {n}")


# ── 4. Обработчик ошибок ─────────────────────────────────────────────────────
async def check_error_handler() -> None:
    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import ErrorEvent, Update

    from app.bot.dp import setup_registrars

    dp = Dispatcher(storage=MemoryStorage())
    setup_registrars(dp)

    event = ErrorEvent(update=Update(update_id=1), exception=RuntimeError("проверка"))
    try:
        result = await dp.errors.trigger(event, dispatcher=dp)
        check("bot: обработчик ошибок перехватывает сбой", result is not False)
    except Exception as exc:
        check("bot: обработчик ошибок перехватывает сбой", False,
              f"{type(exc).__name__}: {exc}")


# ── Главное ──────────────────────────────────────────────────────────────────
async def main() -> int:
    print("=" * 62)
    print("Проверка системы TATU — этап 1 «контур живой»")
    print("=" * 62)
    print(f"База: {_DB_FILE}")
    print()

    await check_db()
    check_web()
    await check_bot()
    await check_error_handler()

    print()
    failed = [r for r in results if not r[1]]
    print(f"Итого: {len(results) - len(failed)} PASS, {len(failed)} FAIL")

    # Закрываем соединения, иначе Windows не даст удалить файл БД
    try:
        from app.database import engine
        await engine.dispose()
    except Exception:
        pass

    if _DB_FILE.exists():
        try:
            _DB_FILE.unlink()
        except PermissionError:
            print(f"(временный файл остался: {_DB_FILE})")

    if failed:
        print("\nНЕ ГОТОВО. Провалено:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1

    print("\nВСЁ ГОТОВО: контур живой.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))