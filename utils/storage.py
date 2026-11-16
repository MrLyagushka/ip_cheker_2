"""Все JSON-данные в одном месте: чтение и атомарная запись.

Файлы: users.json, history.json, tracked.json, settings.json, results/.
Хендлеры файлы напрямую не открывают — только через этот модуль.

Почему без asyncio.Lock: запись синхронная, внутри write_json нет ни одного
await, поэтому другая корутина не может вклиниться в середине записи.
Если когда-нибудь перейдёшь на асинхронный файловый ввод-вывод — верни lock.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

# Кэш известных id: чтобы не писать users.json на каждый апдейт.
KNOWN_USERS: set[int] = set()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        log.exception("Не читается %s", path)
        return default


async def write_json(path: Path, data) -> None:
    """tmp + os.replace: файл либо старый, либо новый, но никогда не битый."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, path)


def init() -> None:
    """Создать папки и пустые файлы. Вызывается один раз при старте."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    for path, default in (
        (config.USERS_FILE, {}),
        (config.HISTORY_FILE, {}),
        (config.TRACKED_FILE, {}),
        (config.SETTINGS_FILE, dict(config.DEFAULT_SETTINGS)),
    ):
        if not path.exists():
            path.write_text(json.dumps(default, ensure_ascii=False, indent=2), "utf-8")
    KNOWN_USERS.clear()
    KNOWN_USERS.update(config.to_int(k, 0) for k in read_json(config.USERS_FILE, {}))
    KNOWN_USERS.discard(0)


# --- пользователи ---------------------------------------------------------

async def register_user(uid: int, username: str | None) -> bool:
    """True, если пользователь новый (и записан на диск)."""
    if uid in KNOWN_USERS:
        return False
    users = read_json(config.USERS_FILE, {})
    users[str(uid)] = {"username": username, "first_seen": now()}
    await write_json(config.USERS_FILE, users)
    KNOWN_USERS.add(uid)
    return True


def all_users() -> dict:
    return read_json(config.USERS_FILE, {})


# --- история сканов -------------------------------------------------------

async def add_history(uid: int, entry: dict) -> None:
    data = read_json(config.HISTORY_FILE, {})
    items = data.get(str(uid), [])
    items.append(entry)
    data[str(uid)] = items[-config.HISTORY_LIMIT:]
    await write_json(config.HISTORY_FILE, data)


def get_history(uid: int) -> list[dict]:
    return read_json(config.HISTORY_FILE, {}).get(str(uid), [])


async def clear_history(uid: int | None = None) -> int:
    """uid=None — очистить всё (админ). Возвращает число удалённых записей."""
    data = read_json(config.HISTORY_FILE, {})
    if uid is None:
        removed = sum(len(v) for v in data.values())
        data = {}
    else:
        removed = len(data.pop(str(uid), []))
    await write_json(config.HISTORY_FILE, data)
    return removed


# --- личный мониторинг ----------------------------------------------------

def get_tracked(uid: int) -> list[dict]:
    return read_json(config.TRACKED_FILE, {}).get(str(uid), [])


def all_tracked() -> dict:
    return read_json(config.TRACKED_FILE, {})


async def save_tracked(data: dict) -> None:
    await write_json(config.TRACKED_FILE, data)


async def add_tracked(uid: int, ip: str) -> str:
    """Возвращает 'ok' | 'dup' | 'limit' — простые строки вместо исключений."""
    data = all_tracked()
    items = data.get(str(uid), [])
    if any(item.get("ip") == ip for item in items):
        return "dup"
    if len(items) >= config.MAX_WATCH:
        return "limit"
    items.append({"ip": ip, "status": "unknown"})
    data[str(uid)] = items
    await save_tracked(data)
    return "ok"


async def remove_tracked(uid: int, index: int) -> str | None:
    """Удаление по индексу из списка НАЖАВШЕГО. Возвращает удалённый ip."""
    data = all_tracked()
    items = data.get(str(uid), [])
    if not 0 <= index < len(items):
        return None
    ip = items.pop(index).get("ip")
    data[str(uid)] = items
    await save_tracked(data)
    return ip


# --- результаты и настройки ----------------------------------------------

def save_result(uid: int, body: str) -> Path:
    """Один файл на пользователя, перезаписывается — старые не копятся."""
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RESULTS_DIR / f"result_{uid}.txt"
    path.write_text(body, "utf-8")
    return path


async def save_settings(patch: dict) -> dict:
    settings = config.load_settings()
    settings.update(patch)
    await write_json(config.SETTINGS_FILE, settings)
    return settings
