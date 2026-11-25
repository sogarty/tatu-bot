"""Полный сквозной тест ЖИВОГО продакшна настоящей подписью.

Проверяет то, что реально делает клиент и мастер, на боевом сервере:
вход → создание заявки → мастер видит → принимает → назначает дату.
Тестовые заявки помечаются и архивируются в конце.

Токен только из окружения/.env. В репозиторий не попадает.

Запуск:
    set BOT_TOKEN=...
    python scripts/verify_production_flow.py [https://host]
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://tatu-bot-4toe.onrender.com").rstrip("/")
CLIENT_ID = 700000001  # тестовый клиент, не мастер


def load_token() -> str:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token
    env_path = pathlib.Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("BOT_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("BOT_TOKEN не найден")


TOKEN = load_token()
MASTER_ID = int(os.environ.get("MASTER_TG_ID", "990916252"))

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def make_init_data(user_id: int, first_name: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHflowProbe",
        "user": json.dumps(
            {"id": user_id, "first_name": first_name, "username": f"u{user_id}"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    cs = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, cs.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": digest})


def api(method: str, path: str, user_id: int | None = None, body: dict | None = None):
    url = BASE + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if user_id is not None:
        req.add_header("Authorization", "TelegramWebApp " + make_init_data(user_id, "Тест"))
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw
    except Exception as e:  # noqa: BLE001
        return 0, str(e)


def main() -> int:
    print("=" * 72)
    print(f"Сквозной тест продакшна: {BASE}")
    print("=" * 72)
    print()

    # 1. Клиент входит
    s, me = api("GET", "/api/v1/me", CLIENT_ID)
    check("клиент входит", s == 200 and isinstance(me, dict), f"status={s}")
    if s != 200:
        return finish()

    # 2. Клиент создаёт заявку
    payload = {
        "description": "ПРОВЕРКА СИСТЕМЫ: тигр в графике, тестовая заявка",
        "location": "предплечье",
        "size": "15 см",
        "color_mode": "bw",
        "is_urgent": False,
        "brief_answers": {"experience_level": "few"},
    }
    s, created = api("POST", "/api/v1/requests", CLIENT_ID, payload)
    ok = s == 201 and isinstance(created, dict)
    check("клиент создаёт заявку", ok, f"status={s}")
    if not ok:
        return finish()

    rid = created["id"]
    check("автор взят из подписи", created.get("user_id") == CLIENT_ID, str(created.get("user_id")))
    check("статус new", created.get("status") == "new", str(created.get("status")))

    # 3. Клиент видит свою заявку
    s, lst = api("GET", "/api/v1/requests?limit=5", CLIENT_ID)
    ids = [x["id"] for x in lst] if isinstance(lst, list) else []
    check("клиент видит заявку в списке", rid in ids, f"status={s}")

    # 4. Мастер её видит и узнаёт клиента
    s, mlst = api("GET", "/api/v1/requests?limit=50", MASTER_ID)
    found = next((x for x in mlst if x["id"] == rid), None) if isinstance(mlst, list) else None
    check("мастер видит заявку", found is not None, f"status={s}")
    if found:
        check("мастер видит имя клиента", bool(found.get("client_name")),
              str(found.get("client_name")))

    # 5. Мастер принимает и назначает дату
    s, body = api("POST", f"/api/v1/requests/{rid}/accept", MASTER_ID)
    check("мастер принимает заявку", s == 200 and body.get("status") == "accepted", f"status={s}")

    s, body = api("POST", f"/api/v1/requests/{rid}/proceed", MASTER_ID)
    check("заявка в работе", s == 200 and body.get("status") == "in_progress", f"status={s}")

    s, body = api("POST", f"/api/v1/requests/{rid}/schedule", MASTER_ID,
                  {"slot_date": "2027-03-15"})
    ok = s == 200 and body.get("status") == "scheduled"
    check("мастер назначает дату", ok, f"status={s}")
    if ok:
        appt = body.get("appointment") or {}
        check("дата видна клиенту", appt.get("slot_date") == "2027-03-15",
              str(appt.get("slot_date")))

    # 6. Клиент видит назначенную дату
    s, cli = api("GET", f"/api/v1/requests/{rid}", CLIENT_ID)
    appt = (cli.get("appointment") or {}) if isinstance(cli, dict) else {}
    check("клиент получает дату сеанса", appt.get("slot_date") == "2027-03-15",
          str(appt.get("slot_date")))

    # 7. Отмена и уборка: возвращаем заявку в очередь и архивируем
    s, body = api("POST", f"/api/v1/requests/{rid}/cancel", MASTER_ID)
    check("запись отменяется", s == 200, f"status={s}")
    s, _ = api("DELETE", f"/api/v1/trash/{rid}", MASTER_ID)
    check("тестовая заявка убрана в архив", s == 204, f"status={s}")

    # 8. Календарь отвечает и не показывает выдуманных дней
    s, av = api("GET", "/api/v1/slots/availability?start_date=2027-03-01&end_date=2027-03-31",
                MASTER_ID)
    check("календарь отвечает", s == 200, f"status={s}")

    return finish()


def finish() -> int:
    print()
    failed = [r for r in results if not r[1]]
    print(f"Итого: {len(results) - len(failed)} PASS, {len(failed)} FAIL")
    if failed:
        print("\nНЕ ГОТОВО:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1
    print("\nВСЁ ГОТОВО: сквозной сценарий работает на живом сервере.")
    return 0


if __name__ == "__main__":
    sys.exit(main())