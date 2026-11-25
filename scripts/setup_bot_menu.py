"""Настройка бота в Telegram (меню, команды, описание) через Bot API.

Все вызовы — UTF-8 JSON, чтобы кириллица не превращалась в «?????».
Токен только из окружения/.env.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

APP_URL = os.environ.get("WEBAPP_URL", "https://tatu-bot-4toe.onrender.com/app/")
MASTER_ID = int(os.environ.get("MASTER_TG_ID", "990916252"))


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


def call(method: str, payload: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return {"ok": False, "http": e.code, "body": body}


def main() -> int:
    print("=== 1. Кнопка меню: открывает приложение ===")
    r = call(
        "setChatMenuButton",
        {"menu_button": {"type": "web_app", "text": "Открыть приложение", "web_app": {"url": APP_URL}}},
    )
    print("set default:", r.get("ok"), r.get("body", ""))
    r = call("getChatMenuButton")
    print("get default:", json.dumps(r.get("result"), ensure_ascii=False))

    print("\n=== 2. Лично мастеру ===")
    r = call(
        "setChatMenuButton",
        {
            "chat_id": MASTER_ID,
            "menu_button": {"type": "web_app", "text": "Открыть приложение", "web_app": {"url": APP_URL}},
        },
    )
    print("set master:", r.get("ok"), r.get("body", ""))
    r = call("getChatMenuButton", None)
    print("get:", json.dumps(r.get("result"), ensure_ascii=False))

    print("\n=== 3. Команды бота ===")
    commands = [{"command": "start", "description": "Открыть приложение и оставить заявку"}]
    r = call("setMyCommands", {"commands": commands})
    print("setMyCommands:", r.get("ok"), r.get("body", ""))
    r = call("getMyCommands")
    print("getMyCommands:", json.dumps(r.get("result"), ensure_ascii=False))

    print("\n=== 4. Описание бота (видно до /start) ===")
    r = call(
        "setMyDescription",
        {
            "description": (
                "Тату-мастер Ариадна ✨\n"
                "Оставь заявку на эскиз, следи за статусом и записывайся на сеанс "
                "прямо в приложении."
            )
        },
    )
    print("setMyDescription:", r.get("ok"), r.get("body", ""))

    print("\n=== 5. Короткое описание ===")
    r = call("setMyShortDescription", {"short_description": "Заявки на тату и запись к мастеру Ариадне ✨"})
    print("setMyShortDescription:", r.get("ok"), r.get("body", ""))

    print("\n=== 6. Финальная сверка ===")
    print("menu:", json.dumps(call("getChatMenuButton").get("result"), ensure_ascii=False))
    print("commands:", json.dumps(call("getMyCommands").get("result"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())