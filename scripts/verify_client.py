"""Проверка клиентского сценария: от входа до создания заявки и кабинета.

Запуск:
    python scripts/verify_client.py

Это НЕ тест «текст файла содержит слово». Здесь поднимается настоящее
приложение с временной базой, генерируется настоящий подписанный
Telegram initData (как его делает Telegram), и запросы идут через HTTP.

Каждая строка PASS — реально выполненное действие.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import pathlib
import sys
import tempfile
import time
from urllib.parse import urlencode

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_DB_FILE = pathlib.Path(tempfile.gettempdir()) / "tatu_verify_client.db"
for suffix in ("", "-journal", "-wal", "-shm"):
    p = pathlib.Path(str(_DB_FILE) + suffix)
    if p.exists():
        p.unlink()

BOT_TOKEN = "123456789:VERIFY_CLIENT_TOKEN"
MASTER_ID = 424242
CLIENT_ID = 777001

os.environ.update(
    {
        "BOT_TOKEN": BOT_TOKEN,
        "MASTER_TG_ID": str(MASTER_ID),
        "MODE": "webhook",
        "ENVIRONMENT": "production",
        "WEBHOOK_BASE_URL": "",
        "WEBHOOK_SECRET": "",
        "WEBAPP_URL": "https://example.test/app/",
        "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE}",
    }
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


# ── Генерация настоящего Telegram initData ──────────────────────────────────


def make_init_data(user_id: int, first_name: str = "Анна") -> str:
    """Собирает initData точно по алгоритму Telegram и подписывает его."""
    user = {"id": user_id, "first_name": first_name, "username": f"u{user_id}"}
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH-test-query",
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
    }

    # data_check_string: по алфавиту, key=value, через \n
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))

    # Secret key: HMAC(key=b"WebAppData", msg=bot_token).
    # ВАЖНО: именно в таком порядке. Перестановка даёт другую подпись,
    # и настоящий Telegram-вход отвергается.
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    # Telegram присылает значения в URL-кодировке — воспроизводим это,
    # иначе тест пройдёт там, где реальный клиент получит 401.
    return urlencode({**params, "hash": h})


def auth(user_id: int) -> dict[str, str]:
    return {"Authorization": f"TelegramWebApp {make_init_data(user_id)}"}


# ── Проверки ────────────────────────────────────────────────────────────────


def main() -> int:
    from fastapi.testclient import TestClient

    from app.main import app

    print("=" * 66)
    print("Проверка клиентского сценария (реальная авторизация Telegram)")
    print("=" * 66)
    print()

    with TestClient(app) as c:
        # 0. Главная защита от прежней ошибки: наша подпись обязана
        #    совпадать с независимой реализацией aiogram. Если формула
        #    снова «перевернётся», этот тест упадёт первым.
        try:
            from aiogram.utils.web_app import check_webapp_signature

            sample = make_init_data(CLIENT_ID)
            check(
                "подпись совпадает с независимой реализацией aiogram",
                check_webapp_signature(BOT_TOKEN, sample),
            )
        except ImportError:  # pragma: no cover
            check("aiogram доступен для сверки подписи", False, "не установлен")

        # 1. Без авторизации — отказ
        r = c.get("/api/v1/me")
        check("без авторизации /me → 401", r.status_code == 401, f"status={r.status_code}")

        # 2. Поддельная подпись — отказ
        r = c.get(
            "/api/v1/me",
            headers={"Authorization": "TelegramWebApp auth_date=1&user={}&hash=deadbeef"},
        )
        check("поддельная подпись → 401", r.status_code == 401, f"status={r.status_code}")

        # 3. Валидная авторизация
        r = c.get("/api/v1/me", headers=auth(CLIENT_ID))
        ok = r.status_code == 200 and r.json().get("user_id") == CLIENT_ID
        check("вход по реальному initData", ok, f"status={r.status_code}, {r.text[:70]}")

        if not ok:
            return finish()

        me = r.json()
        check("клиент не считается мастером", me.get("is_admin") is False, str(me.get("is_admin")))

        # 4. Мастер определяется
        r = c.get("/api/v1/me", headers=auth(MASTER_ID))
        check(
            "мастер распознаётся",
            r.status_code == 200 and r.json().get("is_admin") is True,
            f"status={r.status_code}",
        )

        # 5. Создание заявки клиентом
        payload = {
            "description": "Хочу дракона на предплечье, стиль графика",
            "location": "предплечье",
            "size": "15 см",
            "color_mode": "bw",
            "is_urgent": False,
            "brief_answers": {"experience_level": "many"},
        }
        r = c.post("/api/v1/requests", json=payload, headers=auth(CLIENT_ID))
        ok = r.status_code == 201
        check("клиент создаёт заявку → 201", ok, f"status={r.status_code}, {r.text[:90]}")
        if not ok:
            return finish()

        created = r.json()
        request_id = created["id"]
        check("заявка сразу в статусе new", created["status"] == "new", created["status"])
        check(
            "автор заявки взят из Telegram, а не из тела",
            created["user_id"] == CLIENT_ID,
            f"user_id={created['user_id']}",
        )
        check("анкета сохранилась", created.get("brief_answers") == {"experience_level": "many"},
              str(created.get("brief_answers")))

        # 6. Чужой клиент не видит эту заявку
        r = c.get(f"/api/v1/requests/{request_id}", headers=auth(CLIENT_ID + 1))
        check("чужая заявка → 404", r.status_code == 404, f"status={r.status_code}")

        # 7. Свой список
        r = c.get("/api/v1/requests", headers=auth(CLIENT_ID))
        ok = r.status_code == 200 and len(r.json()) == 1
        check("клиент видит свою заявку в списке", ok, f"status={r.status_code}")

        # 8. Мастер видит заявку
        r = c.get(f"/api/v1/requests/{request_id}", headers=auth(MASTER_ID))
        check("мастер открывает заявку клиента", r.status_code == 200, f"status={r.status_code}")

        # 9. Клиент не может принимать заявки
        r = c.post(f"/api/v1/requests/{request_id}/accept", headers=auth(CLIENT_ID))
        check("клиенту запрещены действия мастера → 403", r.status_code == 403, f"status={r.status_code}")

        # 10. Полный цикл статусов мастером
        steps = [
            ("accept", "accepted"),
            ("proceed", "in_progress"),
        ]
        for action, expected in steps:
            r = c.post(f"/api/v1/requests/{request_id}/{action}", headers=auth(MASTER_ID))
            ok = r.status_code == 200 and r.json().get("status") == expected
            check(f"переход «{action}» → {expected}", ok, f"status={r.status_code}")

        # 11. Назначение даты
        r = c.post(
            f"/api/v1/requests/{request_id}/schedule",
            json={"slot_date": "2026-12-05"},
            headers=auth(MASTER_ID),
        )
        ok = r.status_code == 200 and r.json().get("status") == "scheduled"
        check("назначение даты → scheduled", ok, f"status={r.status_code}, {r.text[:80]}")
        if ok:
            appt = r.json().get("appointment") or {}
            check("дата сеанса видна клиенту", appt.get("slot_date") == "2026-12-05",
                  str(appt.get("slot_date")))

        # 12. Завершение
        r = c.post(f"/api/v1/requests/{request_id}/complete", headers=auth(MASTER_ID))
        ok = r.status_code == 200 and r.json().get("status") == "completed"
        check("завершение сеанса → completed", ok, f"status={r.status_code}")

        # 13. Слот занят в календаре
        r = c.get(
            "/api/v1/slots/availability?start_date=2026-12-01&end_date=2026-12-31"
        )
        ok = r.status_code == 200
        days = (r.json().get("days") or []) if ok else []
        busy = [d for d in days if d.get("is_booked")]
        check("календарь показывает занятую дату", bool(busy), f"занято: {len(busy)}")
        if busy:
            check("занятая дата — 5 декабря", busy[0]["date"] == "2026-12-05", busy[0]["date"])

        # 14. Дашборд мастера
        r = c.get("/api/v1/admin/dashboard", headers=auth(MASTER_ID))
        ok = r.status_code == 200
        check("дашборд мастера доступен", ok, f"status={r.status_code}")
        if ok:
            d = r.json()
            check("дашборд посчитал завершённую заявку", d.get("completed_count") == 1,
                  str(d.get("completed_count")))

        # 15. Клиенту дашборд запрещён
        r = c.get("/api/v1/admin/dashboard", headers=auth(CLIENT_ID))
        check("клиенту закрыт дашборд → 403", r.status_code == 403, f"status={r.status_code}")

        # 16. Валидация входных данных
        r = c.post(
            "/api/v1/requests",
            json={"description": "мало", "location": "a", "size": "", "color_mode": "bw"},
            headers=auth(CLIENT_ID),
        )
        check("слишком короткое описание → 422", r.status_code == 422, f"status={r.status_code}")

        r = c.post(
            "/api/v1/requests",
            json={**payload, "color_mode": "neon"},
            headers=auth(CLIENT_ID),
        )
        check("недопустимый цвет → 422", r.status_code == 422, f"status={r.status_code}")

        # 17. Мастер ставит дату в календаре
        r = c.post(
            "/api/v1/slots/2026-12-20/toggle", headers=auth(MASTER_ID)
        )
        ok = r.status_code == 200 and r.json().get("is_blocked") is True
        check("мастер закрывает день в календаре", ok, f"status={r.status_code}")
        r = c.post("/api/v1/slots/2026-12-20/toggle", headers=auth(MASTER_ID))
        ok = r.status_code == 200 and r.json().get("is_blocked") is False
        check("мастер открывает день обратно", ok, f"status={r.status_code}")

        # 18. Страница приложения отдаётся с нужными скриптами
        r = c.get("/app/")
        html = r.text
        check("страница приложения открывается", r.status_code == 200, f"{len(html)} байт")
        check("подключён telegram-web-app.js", "telegram-web-app.js" in html)
        check("в приложении нет «Арину»", "Арину" not in html)
        check("в приложении нет «Арин»", "Арин" not in html)
        for name in ("app.js", "style.css"):
            r2 = c.get(f"/app/{name}")
            check(f"{name} отдаётся", r2.status_code == 200 and len(r2.text) > 1000,
                  f"status={r2.status_code}, {len(r2.text)} байт")

        # ── Настройки: запись не должна падать ───────────────────────────
        # Раньше PUT /settings сохранял значение, но отвечал 500 из-за
        # отложенной подгрузки updated_at (MissingGreenlet).
        r = c.put("/api/v1/settings", json={"urgent_price": 1500}, headers=auth(MASTER_ID))
        ok = r.status_code == 200 and r.json().get("urgent_price") == 1500
        check("мастер сохраняет цену срочности", ok, f"status={r.status_code}")
        if ok:
            check("ответ содержит updated_at", bool(r.json().get("updated_at")))

        r = c.put("/api/v1/settings", json={"urgent_price": 0}, headers=auth(CLIENT_ID))
        check("клиенту запрещено менять настройки → 403", r.status_code == 403,
              f"status={r.status_code}")

        r = c.get("/api/v1/settings")
        check("цена срочности видна клиенту", r.status_code == 200,
              f"urgent_price={r.json().get('urgent_price')}")

        # ── Клиент в карточке мастера ────────────────────────────────────
        # Старый бот показывал имя клиента; кабинет не должен его терять.
        r = c.get("/api/v1/requests", headers=auth(MASTER_ID))
        ok = r.status_code == 200 and len(r.json()) > 0
        check("мастер получает список заявок", ok, f"status={r.status_code}")
        if ok:
            first = r.json()[0]
            check("в заявке есть имя клиента", bool(first.get("client_name")),
                  str(first.get("client_name")))
            check("в заявке есть username клиента", "client_username" in first,
                  str(first.get("client_username")))

        # ── Календарь мастера: открыть/закрыть день ─────────────────────
        r = c.post("/api/v1/slots/2027-01-15/toggle", headers=auth(MASTER_ID))
        ok = r.status_code == 200 and r.json().get("is_blocked") is True
        check("мастер закрывает день", ok, f"status={r.status_code}")
        r = c.get("/api/v1/slots/availability?start_date=2027-01-01&end_date=2027-01-31")
        days = {d["date"]: d for d in (r.json().get("days") or [])}
        check("закрытый день виден в календаре",
              days.get("2027-01-15", {}).get("is_blocked") is True,
              str(days.get("2027-01-15")))

        # ── Клиенту календарь менять нельзя ──────────────────────────────
        r = c.post("/api/v1/slots/2027-01-16/toggle", headers=auth(CLIENT_ID))
        check("клиенту запрещено менять календарь → 403", r.status_code == 403,
              f"status={r.status_code}")

        # ── Занятый день не должен показываться свободным ────────────────
        # После завершения сеанса запись получает статус done, но день
        # по-прежнему занят: нельзя записать туда второго клиента.
        r = c.get("/api/v1/slots/availability?start_date=2026-12-01&end_date=2026-12-31")
        days = {d["date"]: d for d in (r.json().get("days") or [])}
        check("день завершённого сеанса остаётся занятым",
              days.get("2026-12-05", {}).get("is_booked") is True,
              str(days.get("2026-12-05")))

        # ── Страница: разметка без дублей атрибута class ─────────────────
        check("нет дублирующегося атрибута class в index.html",
              'class="detail-section" id="detail-rejection-section" class=' not in html)

        # ── Архив: заявка, убранная мастером, исчезает у клиента ─────────
        # Раньше DELETE /trash только помечал is_archived, но список
        # возвращал её снова — клиент видел «удалённую» заявку.
        r = c.post("/api/v1/requests", headers=auth(CLIENT_ID), json={
            "description": "Проверка архива: тигр",
            "location": "рука",
            "size": "10 см",
            "color_mode": "color",
            "is_urgent": False,
        })
        archived_id = r.json()["id"]
        r = c.delete(f"/api/v1/trash/{archived_id}", headers=auth(MASTER_ID))
        check("мастер убирает заявку в архив → 204", r.status_code == 204,
              f"status={r.status_code}")

        r = c.get("/api/v1/requests?limit=100", headers=auth(CLIENT_ID))
        ids = [x["id"] for x in r.json()]
        check("архивная заявка НЕ видна клиенту", archived_id not in ids,
              f"ids={ids}")

        # ── Здоровье: диагностика видна, а не спрятана ──────────────────
        r = c.get("/api/v1/health")
        body = r.json() if r.status_code == 200 else {}
        check("health отвечает 200", r.status_code == 200, f"status={r.status_code}")
        check("health сообщает тип базы", bool(body.get("database_backend")),
              str(body.get("database_backend")))
        check("health сообщает о сохранности данных",
              "data_persistent" in body, str(body.get("data_persistent")))

    return finish()


def finish() -> int:
    print()
    failed = [x for x in results if not x[1]]
    print(f"Итого: {len(results) - len(failed)} PASS, {len(failed)} FAIL")

    try:
        from app.database import engine

        asyncio.get_event_loop().run_until_complete(engine.dispose())
    except Exception:
        pass

    for suffix in ("", "-journal", "-wal", "-shm"):
        p = pathlib.Path(str(_DB_FILE) + suffix)
        if p.exists():
            try:
                p.unlink()
            except PermissionError:
                pass

    if failed:
        print("\nНЕ ГОТОВО. Провалено:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1

    print("\nВСЁ ГОТОВО: клиентский сценарий работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())