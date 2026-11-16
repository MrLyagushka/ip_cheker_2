"""Настройки: ТОЛЬКО чтение .env и settings.json.

Ничего не создаёт: Bot и Dispatcher собираются в main.py.
.env          — секреты и стартовые значения (не меняются на ходу).
settings.json — то, что админ меняет в рантайме (лимит пингов, прокси).
"""
from __future__ import annotations

import json
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


def _get(key: str, default: str = "") -> str:
    """Приоритет: переменная окружения -> .env -> default."""
    return os.getenv(key) or _file_env.get(key) or default


TOKEN = _get("TOKEN")
ADMIN_ID = to_int(_get("ADMIN_ID"), 0)          # 0 = админка выключена
ALERT_CHAT_ID = to_int(_get("ALERT_CHAT_ID"), 0)      # супергруппа для алертов, 0 = не слать
ALERT_THREAD_ID = to_int(_get("ALERT_THREAD_ID"), 0)  # id темы (topic) в супергруппе, 0 = без темы
PROXY_URL = _get("PROXY_URL")                   # ТОЛЬКО для связи бота с Telegram
DATA_DIR = Path(_get("DATA_DIR", str(ROOT / "data")))

CHECK_INTERVAL = to_int(_get("CHECK_INTERVAL"), 3600)  # секунд между тиками мониторинга
PING_LIMIT_DEFAULT = to_int(_get("PING_LIMIT"), 32)    # одновременных пингов
MAX_WATCH = to_int(_get("MAX_WATCH"), 20)              # IP в мониторинге на юзера
HISTORY_LIMIT = 50                                     # записей истории на юзера
PING_LIMIT_MAX = 256

USERS_FILE = DATA_DIR / "users.json"
HISTORY_FILE = DATA_DIR / "history.json"
TRACKED_FILE = DATA_DIR / "tracked.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
RESULTS_DIR = DATA_DIR / "results"
LOG_FILE = DATA_DIR / "logs" / "bot.log"

DEFAULT_SETTINGS = {"ping_limit": PING_LIMIT_DEFAULT, "proxy": PROXY_URL}


def load_settings() -> dict:
    """Читается заново при каждом вызове: админ мог поменять файл."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(SETTINGS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        stored = None
    if isinstance(stored, dict):
        settings.update(stored)
    settings["ping_limit"] = max(
        1, min(PING_LIMIT_MAX, to_int(settings.get("ping_limit"), PING_LIMIT_DEFAULT))
    )
    return settings
