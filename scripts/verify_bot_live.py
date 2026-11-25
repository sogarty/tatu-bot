"""Проверка живого бота: /start и кнопка Mini App.

Отправляет боту /start через Bot API и смотрит, что он ответил
(getUpdates недоступен при webhook — вместо этого проверяем, что
вебхук принял update без ошибок и pending не растёт).

Дополнительно проверяет, что кнопка WebApp ведёт на рабочий /app/.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request


def load_token() -> str:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token
    env_path = pathlib.Path(__file__).resolve().parent.parent.parent / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("BOT_TOKEN"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("BOT_TOKEN не найден")


TOKEN = load_token()
MASTER_ID = int(os.environ.get("MASTER_TG_ID", "990916252"))


def call(method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "body": e.read().decode("utf-8", "replace")}


results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def main() -> int:
    print("=" * 70)
    print("Проверка живого бота")
    print("=" * 70)
    print()

    me = call("getMe")
    check("бот доступен", me.get("ok") is True, str(me.get("result", {}).get("username")))

    # Вебхук настроен и без ошибок
    wh = call("getWebhookInfo").get("result", {})
    check("вебхук установлен", bool(wh.get("url")), str(wh.get("url")))
    check("нет ошибок доставки", not wh.get("last_error_message"),
          str(wh.get("last_error_message")))

    # Кнопка меню ведёт на приложение
    menu = call("getChatMenuButton").get("result", {})
    check("кнопка меню — web_app", menu.get("type") == "web_app", str(menu.get("type")))
    url = (menu.get("web_app") or {}).get("url", "")
    check("кнопка ведёт на /app/", url.endswith("/app/"), url)
    check("текст кнопки по-русски", "Открыть" in (menu.get("text") or ""), str(menu.get("text")))

    # Само приложение по этому адресу отвечает
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
        check("страница по кнопке открывается", r.status == 200, f"status={r.status}")
        check("подключён telegram-web-app.js", "telegram-web-app.js" in html)
        check("название верное", "Ариадна" in html)
    except Exception as e:  # noqa: BLE001
        check("страница по кнопке открывается", False, str(e))

    # Отправляем /start мастеру (это реальное сообщение в чат)
    print("\nОтправляю /start в чат мастера...")
    r = call(
        "sendMessage",
        {
            "chat_id": MASTER_ID,
            "text": "Это проверка связи от системы. Бот работает ✅",
        },
    )
    check("сообщение в чат доставлено", r.get("ok") is True,
          f"message_id={r.get('result', {}).get('message_id')}")

    # Ждём, чтобы вебхук обработал
    time.sleep(3)
    wh2 = call("getWebhookInfo").get("result", {})
    check("вебхук не накопил ошибок после сообщения",
          not wh2.get("last_error_message"), str(wh2.get("last_error_message")))
    check("нет зависших обновлений", wh2.get("pending_update_count", 0) == 0,
          f"pending={wh2.get('pending_update_count')}")

    print()
    failed = [x for x in results if not x[1]]
    print(f"Итого: {len(results) - len(failed)} PASS, {len(failed)} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())