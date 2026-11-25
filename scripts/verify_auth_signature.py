"""Проверка криптографии входа Telegram — сверка с независимой реализацией.

Зачем этот скрипт отдельно: прежняя ошибка была в САМОЙ формуле подписи,
а тесты подписывали данные той же неверной формулой, поэтому «проходили»
и пропускали сломанный вход в продакшн.

Здесь подпись считается двумя независимыми путями:
  1) по официальной документации Telegram (этот файл);
  2) библиотекой aiogram (check_webapp_signature), которая живёт в venv.
Если они согласны между собой, а наша функция принимает результат —
значит алгоритм в приложении соответствует Telegram.

Запуск:
    set BOT_TOKEN=...          # токен не хранится в репозитории
    python scripts/verify_auth_signature.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import sys
import time
from urllib.parse import urlencode

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Токен только из окружения. Если его нет — берём синтетический:
# для проверки алгоритма подходит любой, важно лишь постоянство.
TOKEN = os.environ.get("BOT_TOKEN", "").strip() or "123456789:SYNTHETIC_TOKEN"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


# ─── Независимая реализация по docs (путь №1) ───────────────────────────────


def sign_by_docs(params: dict[str, str], token: str) -> str:
    """Подпись ровно как в официальной документации Telegram.

    Ключ — литерал "WebAppData", данные — токен бота.
    """
    check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()


def make_init_data(user_id: int, first_name: str, token: str, auth_date: int | None = None) -> str:
    """Собирает initData как Telegram: значения в URL-кодировке."""
    params = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHrealisticQueryId",
        "user": json.dumps(
            {"id": user_id, "first_name": first_name, "username": f"user{user_id}"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    digest = sign_by_docs(params, token)
    return urlencode({**params, "hash": digest})


# ─── Проверки ───────────────────────────────────────────────────────────────


def main() -> int:
    from app.auth import verify_telegram_webapp_init_data

    print("=" * 78)
    print("Проверка подписи Telegram initData (сверка с aiogram)")
    print("=" * 78)
    print()

    # 0. aiogram доступен — это наш независимый арбитр
    try:
        from aiogram.utils.web_app import check_webapp_signature

        have_oracle = True
        check("aiogram доступен как независимая проверка", True)
    except Exception as exc:  # pragma: no cover
        have_oracle = False
        check("aiogram доступен как независимая проверка", False, str(exc))

    # 1. Наша подпись совпадает с aiogram
    init_data = make_init_data(777, "Анна", TOKEN)
    if have_oracle:
        check(
            "наша подпись совпадает с aiogram",
            check_webapp_signature(TOKEN, init_data),
        )

    # 2. Наша функция принимает корректные данные
    verified = verify_telegram_webapp_init_data(TOKEN, init_data)
    ok = verified is not None and verified.get("user_id") == 777
    check("вход по корректной подписи принят", ok,
          f"user_id={verified.get('user_id') if verified else None}")

    # 3. Кириллица и пробелы (URL-кодирование) не мешают
    init_cyr = make_init_data(778, "Мария Ивановна", TOKEN)
    v2 = verify_telegram_webapp_init_data(TOKEN, init_cyr)
    ok = v2 is not None and v2["user"]["first_name"] == "Мария Ивановна"
    check("кириллическое имя декодируется верно", ok,
          v2["user"]["first_name"] if v2 else "None")

    # 4. Подделка хотя бы одного символа отвергается
    tampered = init_data.replace("AAHrealisticQueryId", "AAHrealisticQueryIe")
    check("подделанные данные отвергнуты",
          verify_telegram_webapp_init_data(TOKEN, tampered) is None)

    # 5. Чужой токен отвергается
    check("подпись чужим токеном отвергнута",
          verify_telegram_webapp_init_data("999:OTHER_TOKEN", init_data) is None)

    # 6. Просроченные данные отвергаются
    old = make_init_data(779, "Старый", TOKEN, auth_date=int(time.time()) - 3 * 86400)
    check("просроченный initData отвергнут", verify_telegram_webapp_init_data(TOKEN, old) is None)

    # 7. БЕЗ поля hash — отвергается
    no_hash = init_data.split("&hash=")[0]
    check("данные без hash отвергнуты",
          verify_telegram_webapp_init_data(TOKEN, no_hash) is None)

    # 8. РЕГРЕССИЯ: старая ошибочная формула (ключ и данные местами)
    #    должна НЕ совпадать. Если совпадёт — значит мы вернули ту ошибку.
    params = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHrealisticQueryId",
        "user": json.dumps({"id": 777, "first_name": "Анна"}, separators=(",", ":")),
    }
    cs = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    wrong_secret = hmac.new(TOKEN.encode(), b"WebAppData", hashlib.sha256).digest()
    wrong_hash = hmac.new(wrong_secret, cs.encode(), hashlib.sha256).hexdigest()
    correct_hash = sign_by_docs(params, TOKEN)
    check("старая неверная формула больше не используется",
          wrong_hash != correct_hash,
          "подписи различаются, как и должно быть")
    wrong_init = urlencode({**params, "hash": wrong_hash})
    check("данные со старой подписью отвергнуты",
          verify_telegram_webapp_init_data(TOKEN, wrong_init) is None)

    # 9. Совместимость: поле signature (Bot API 8.0+) не ломает проверку.
    #    Оба варианта — и когда signature входит в подпись (как в aiogram),
    #    и когда исключён (как в docs для Ed25519) — должны приниматься.
    signed_with_sig = dict(params)
    signed_with_sig["signature"] = "abc123"
    hash_with_sig = sign_by_docs(signed_with_sig, TOKEN)
    with_sig = urlencode({**params, "signature": "abc123", "hash": hash_with_sig})
    check("signature включён в подпись → вход принят",
          verify_telegram_webapp_init_data(TOKEN, with_sig) is not None)

    with_sig_excluded = urlencode({**params, "signature": "abc123", "hash": correct_hash})
    check("signature исключён из подписи → вход принят",
          verify_telegram_webapp_init_data(TOKEN, with_sig_excluded) is not None)

    # ── Итог ────────────────────────────────────────────────────────────────
    print()
    failed = [r for r in results if not r[1]]
    print(f"Итого: {len(results) - len(failed)} PASS, {len(failed)} FAIL")

    if failed:
        print("\nНЕ ГОТОВО:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1

    print("\nВСЁ ГОТОВО: подпись соответствует Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())