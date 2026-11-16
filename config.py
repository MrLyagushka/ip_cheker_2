"""Настройки: ТОЛЬКО чтение .env и settings.json.

Ничего не создаёт: Bot и Dispatcher собираются в main.py.
.env          — секреты и стартовые значения (не меняются на ходу).
settings.json — то, что админ меняет в рантайме (лимит пингов, прокси).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def parse_env(text: str) -> dict[str, str]:
    """Мини-парсер .env: KEY=VALUE, комментарии #, кавычки. Без зависимостей."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def to_int(value, default: int) -> int:
    """Целое или значение по умолчанию (мусор в .env не должен ронять бота)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


ENV_FILE = Path(os.getenv("ENV_FILE") or ROOT / ".env")
try:
    _file_env = parse_env(ENV_FILE.read_text("utf-8"))
except OSError:
    _file_env = {}


def unquote(value: str) -> str:
    """Снимает обрамляющие кавычки и пробелы.

    Зачем: docker compose / systemd / PowerShell могут передать значение
    ВМЕСТЕ с кавычками. Строка '"socks5://..."' ломает парсер прокси
    (ValueError: Invalid scheme component) и бот не стартует.
    """
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def _get(key: str, default: str = "") -> str:
    """Приоритет: переменная окружения -> .env -> default. Кавычки снимаем всегда."""
    return unquote(os.getenv(key) or _file_env.get(key) or default)


TOKEN = _get("TOKEN")
ADMIN_ID = to_int(_get("ADMIN_ID"), 0)          # 0 = админка выключена
ALERT_CHAT_ID = to_int(_get("ALERT_CHAT_ID"), 0)      # супергруппа для алертов, 0 = не слать
ALERT_THREAD_ID = to_int(_get("ALERT_THREAD_ID"), 0)  # id темы (topic) в супергруппе, 0 = без темы
PROXY_URL = _get("PROXY_URL")                   # ТОЛЬКО для связи бота с Telegram
DATA_DIR = Path(_get("DATA_DIR", str(ROOT / "data")))

CHECK_INTERVAL = to_int(_get("CHECK_INTERVAL"), 3600)  # секунд между тиками мониторинга
PING_LIMIT_DEFAULT = to_int(_get("PING_LIMIT"), 32)    # одновременных пингов
MAX_WATCH = to_int(_get("MAX_WATCH"), 20)              # IP в мониторинге на юзера
PROXY_PORT = to_int(_get("PROXY_PORT"), 1080)          # порт SOCKS5 в команде участника
PROXY_CHECK_INTERVAL = to_int(_get("PROXY_CHECK_INTERVAL"), 60)  # секунд между проверками прокси
PROXY_WAIT_HOURS = to_int(_get("PROXY_WAIT_HOURS"), 24)          # сколько ждём запуска прокси
PROXY_MAX_PER_USER = to_int(_get("PROXY_MAX_PER_USER"), 3)       # заявок на одного участника
HISTORY_LIMIT = 50                                     # записей истории на юзера
PING_LIMIT_MAX = 256

DB_FILE = DATA_DIR / "bot.db"          # ВСЕ данные здесь (SQLite, WAL)
RESULTS_DIR = DATA_DIR / "results"     # txt-отчёты по /24
LOG_FILE = DATA_DIR / "logs" / "bot.log"

# Старые JSON-файлы: если найдены при старте — перенесём в БД один раз.
LEGACY_FILES = {
    "users": DATA_DIR / "users.json",
    "history": DATA_DIR / "history.json",
    "tracked": DATA_DIR / "tracked.json",
    "settings": DATA_DIR / "settings.json",
}

DEFAULT_SETTINGS = {"ping_limit": PING_LIMIT_DEFAULT, "proxy": PROXY_URL}


def clamp_limit(value) -> int:
    """Лимит пингов всегда в разумных пределах, что бы ни пришло из БД."""
    return max(1, min(PING_LIMIT_MAX, to_int(value, PING_LIMIT_DEFAULT)))
