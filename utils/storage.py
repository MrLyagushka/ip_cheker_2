"""Хранилище: один файл SQLite (data/bot.db). Публичный API прежний.

Почему SQLite, а не JSON: запись транзакционная, файл не бьётся при выключении
питания, ничего не теряется между запусками. В Docker файл лежит в томе.

Все вызовы синхронные и очень короткие (локальная БД), поэтому event loop
они не блокируют заметным образом. Функции оставлены async — чтобы вызывающий
код не менялся.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None
KNOWN_USERS: set[int] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    uid INTEGER PRIMARY KEY, username TEXT, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER, ts TEXT, type TEXT, target TEXT, up INTEGER, total INTEGER
);
CREATE INDEX IF NOT EXISTS history_uid ON history(uid);
CREATE TABLE IF NOT EXISTS tracked (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid INTEGER, ip TEXT, status TEXT DEFAULT 'unknown',
    UNIQUE(uid, ip)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS proxies (
    id TEXT PRIMARY KEY, owner INTEGER, owner_name TEXT,
    host TEXT, port INTEGER, login TEXT, password TEXT,
    status TEXT DEFAULT 'waiting', created TEXT, last_check TEXT
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def db() -> sqlite3.Connection:
    """Ленивое подключение: схема создаётся сама, отдельный init не обязателен."""
    global _conn
    if _conn is None:
        config.DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_FILE, isolation_level=None, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")     # переживает перезапуск процесса
        _conn.execute("PRAGMA synchronous=FULL")     # переживает выключение питания
        _conn.executescript(SCHEMA)
    return _conn


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def rows(sql: str, params=()) -> list[dict]:
    return [dict(row) for row in db().execute(sql, params).fetchall()]


def run(sql: str, params=()):
    return db().execute(sql, params)


def init() -> None:
    """Создать БД, перенести старые JSON (один раз), прогреть кэш пользователей."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    db()
    migrate_json()
    KNOWN_USERS.clear()
    KNOWN_USERS.update(row["uid"] for row in rows("SELECT uid FROM users"))


def migrate_json() -> int:
    """Перенос данных из старой JSON-версии. Файлы переименовываем в .migrated."""
    moved = 0
    for kind, path in config.LEGACY_FILES.items():
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            log.exception("Не читается старый файл %s", path)
            continue
        if kind == "users":
            for uid, info in data.items():
                run("INSERT OR IGNORE INTO users(uid, username, first_seen) VALUES(?,?,?)",
                    (config.to_int(uid, 0), info.get("username"), info.get("first_seen") or now()))
                moved += 1
        elif kind == "history":
            for uid, items in data.items():
                for item in items:
                    run("INSERT INTO history(uid, ts, type, target, up, total) VALUES(?,?,?,?,?,?)",
                        (config.to_int(uid, 0), item.get("ts"), item.get("type"),
                         item.get("target"), item.get("up", 0), item.get("total", 0)))
                    moved += 1
        elif kind == "tracked":
            for uid, items in data.items():
                for item in items:
                    run("INSERT OR IGNORE INTO tracked(uid, ip, status) VALUES(?,?,?)",
                        (config.to_int(uid, 0), item.get("ip"), item.get("status", "unknown")))
                    moved += 1
        elif kind == "settings":
            for key, value in data.items():
                run("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, str(value)))
                moved += 1
        path.rename(path.with_suffix(path.suffix + ".migrated"))
    if moved:
        log.info("Перенесено из JSON в SQLite: %s записей", moved)
    return moved


# --- пользователи ---------------------------------------------------------

async def register_user(uid: int, username: str | None) -> bool:
    if uid in KNOWN_USERS:
        return False
    run("INSERT OR REPLACE INTO users(uid, username, first_seen) VALUES(?,?,?)", (uid, username, now()))
    KNOWN_USERS.add(uid)
    return True


def all_users() -> dict:
    return {str(row["uid"]): row for row in rows("SELECT * FROM users")}


# --- история сканов -------------------------------------------------------

async def add_history(uid: int, entry: dict) -> None:
    run("INSERT INTO history(uid, ts, type, target, up, total) VALUES(?,?,?,?,?,?)",
        (uid, entry.get("ts") or now(), entry.get("type"), entry.get("target"),
         entry.get("up", 0), entry.get("total", 0)))
    run("DELETE FROM history WHERE uid=? AND id NOT IN "
        "(SELECT id FROM history WHERE uid=? ORDER BY id DESC LIMIT ?)",
        (uid, uid, config.HISTORY_LIMIT))


def get_history(uid: int) -> list[dict]:
    return rows("SELECT ts, type, target, up, total FROM history WHERE uid=? ORDER BY id", (uid,))


def all_history() -> dict:
    result: dict[str, list] = {}
    for row in rows("SELECT uid, ts, type, target, up, total FROM history ORDER BY id"):
        result.setdefault(str(row.pop("uid")), []).append(row)
    return result


async def clear_history(uid: int | None = None) -> int:
    if uid is None:
        cursor = run("DELETE FROM history")
    else:
        cursor = run("DELETE FROM history WHERE uid=?", (uid,))
    return cursor.rowcount


# --- личный мониторинг ----------------------------------------------------

def get_tracked(uid: int) -> list[dict]:
    return rows("SELECT ip, status FROM tracked WHERE uid=? ORDER BY id", (uid,))


def all_tracked() -> dict:
    result: dict[str, list] = {}
    for row in rows("SELECT uid, ip, status FROM tracked ORDER BY id"):
        result.setdefault(str(row.pop("uid")), []).append(row)
    return result


async def save_tracked(data: dict) -> None:
    """Обновляем только статусы: удалённые пользователями записи не воскрешаем."""
    for uid, items in data.items():
        for item in items:
            run("UPDATE tracked SET status=? WHERE uid=? AND ip=?",
                (item.get("status"), config.to_int(uid, 0), item.get("ip")))


async def add_tracked(uid: int, ip: str) -> str:
    if run("SELECT 1 FROM tracked WHERE uid=? AND ip=?", (uid, ip)).fetchone():
        return "dup"
    count = run("SELECT COUNT(*) AS c FROM tracked WHERE uid=?", (uid,)).fetchone()["c"]
    if count >= config.MAX_WATCH:
        return "limit"
    run("INSERT INTO tracked(uid, ip, status) VALUES(?,?, 'unknown')", (uid, ip))
    return "ok"


async def remove_tracked(uid: int, index: int) -> str | None:
    items = get_tracked(uid)
    if not 0 <= index < len(items):
        return None
    ip = items[index]["ip"]
    run("DELETE FROM tracked WHERE uid=? AND ip=?", (uid, ip))
    return ip


# --- настройки (то, что админ меняет на ходу) -----------------------------

def load_settings() -> dict:
    settings = dict(config.DEFAULT_SETTINGS)
    for row in rows("SELECT key, value FROM settings"):
        settings[row["key"]] = row["value"]
    settings["ping_limit"] = config.clamp_limit(settings.get("ping_limit"))
    return settings


async def save_settings(patch: dict) -> dict:
    for key, value in patch.items():
        run("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", (key, "" if value is None else str(value)))
    return load_settings()


# --- прокси участников ----------------------------------------------------

def add_proxy(record: dict) -> dict:
    run("INSERT INTO proxies(id, owner, owner_name, host, port, login, password, status, created, last_check) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (record["id"], record["owner"], record["owner_name"], record["host"], record["port"],
         record["login"], record["password"], record.get("status", "waiting"),
         record.get("created") or now(), record.get("last_check", "")))
    return record


def all_proxies() -> list[dict]:
    return rows("SELECT * FROM proxies ORDER BY created")


def get_proxy(proxy_id: str) -> dict | None:
    found = rows("SELECT * FROM proxies WHERE id=?", (proxy_id,))
    return found[0] if found else None


def set_proxy_status(proxy_id: str, status: str) -> None:
    run("UPDATE proxies SET status=?, last_check=? WHERE id=?", (status, now(), proxy_id))


def remove_proxy(proxy_id: str) -> bool:
    return run("DELETE FROM proxies WHERE id=?", (proxy_id,)).rowcount > 0


# --- файлы результатов ----------------------------------------------------

def save_result(uid: int, body: str) -> Path:
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.RESULTS_DIR / f"result_{uid}.txt"
    path.write_text(body, "utf-8")
    return path
