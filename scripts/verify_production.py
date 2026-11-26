"""Пробник продакшна: настоящая подпись реальным токеном.

Берёт токен из .env (в репозиторий не попадает), подписывает initData
точно по алгоритму Telegram и обращается к живому API.

Использование:
    python scripts/probe_production.py https://host
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


def make_init_data(token: str, user_id: int, first_name: str) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHproductionProbe",
        "user": json.dumps(
            {"id": user_id, "first_name": first_name, "username": f"u{user_id}"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": digest})


def call(base: str, path: str, init_data: str | None) -> tuple[int, str]:
    req = urllib.request.Request(base.rstrip("/") + path)
    if init_data:
        req.add_header("Authorization", "TelegramWebApp " + init_data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "https://tatu-bot-4toe.onrender.com"
    token = load_token()

    # ID мастера из окружения/по умолчанию
    master_id = int(os.environ.get("MASTER_TG_ID", "990916252"))

    print("=" * 70)
    print(f"Проверка живого API: {base}")
    print("=" * 70)

    results = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))

    status, body = call(base, "/api/v1/me", None)
    check("без авторизации → 401", status == 401, f"status={status}")

    status, body = call(base, "/api/v1/health", None)
    try:
        health = json.loads(body)
    except (TypeError, json.JSONDecodeError):
        health = {}
    check("health → 200", status == 200, f"status={status}")
    check("production использует постоянную БД",
          status == 200 and health.get("data_persistent") is True,
          str(health))

    status, body = call(base, "/api/v1/me", "auth_date=1&user=%7B%7D&hash=deadbeef")
    check("поддельная подпись → 401", status == 401, f"status={status}")

    init_data = make_init_data(token, master_id, "Ариадна")
    status, body = call(base, "/api/v1/me", init_data)
    ok = status == 200
    check("вход по настоящей подписи → 200", ok, f"status={status} {body[:120]}")

    if ok:
        try:
            data = json.loads(body)
            check("мастер распознан", data.get("is_admin") is True, str(data.get("is_admin")))
            check("id совпадает", data.get("user_id") == master_id, str(data.get("user_id")))
        except json.JSONDecodeError:
            check("ответ разбирается как JSON", False, body[:80])

        status, body = call(base, "/api/v1/requests?limit=3", init_data)
        check("мастер видит список заявок", status == 200, f"status={status}")

        status, body = call(base, "/api/v1/slots/availability", init_data)
        check("календарь отвечает", status == 200, f"status={status}")

    print()
    failed = sum(1 for r in results if not r)
    print(f"Итого: {len(results) - failed} PASS, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
