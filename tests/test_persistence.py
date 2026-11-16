"""Данные не должны теряться между запусками: SQLite + том Docker."""
import asyncio

import config
from utils import storage


def fill():
    async def scenario():
        await storage.register_user(42, "owner")
        await storage.add_history(42, {"ts": "t", "type": "subnet", "target": "10.0.0.0/24", "up": 5, "total": 256})
        await storage.add_tracked(42, "8.8.8.8")
        await storage.save_settings({"ping_limit": 24, "proxy": "socks5://h:1"})

    asyncio.run(scenario())
    storage.add_proxy({"id": "px1", "owner": 42, "owner_name": "owner", "host": "1.2.3.4", "port": 1080,
                       "login": "u", "password": "p", "status": "up", "created": storage.now(), "last_check": ""})


def test_data_survives_restart(data):
    fill()
    storage.close()          # «остановили бота»
    storage.KNOWN_USERS.clear()
    storage.init()           # «запустили снова» — тот же файл БД

    assert "42" in storage.all_users()
    assert storage.get_history(42)[0]["target"] == "10.0.0.0/24"
    assert storage.get_tracked(42)[0]["ip"] == "8.8.8.8"
    assert storage.load_settings()["ping_limit"] == 24
    assert storage.load_settings()["proxy"] == "socks5://h:1"
    assert storage.get_proxy("px1")["status"] == "up"
    assert 42 in storage.KNOWN_USERS


def test_data_survives_hard_process_death(data):
    """Без close(): имитируем kill -9 — транзакции уже на диске (synchronous=FULL)."""
    fill()
    storage._conn = None     # соединение «оборвалось», корректного закрытия не было
    storage.init()
    assert "42" in storage.all_users()
    assert storage.get_proxy("px1") is not None


def test_db_lives_in_data_dir(data):
    assert config.DB_FILE.parent == config.DATA_DIR
    assert config.DB_FILE.name == "bot.db"


def test_second_open_reads_same_file(data):
    fill()
    import sqlite3

    connection = sqlite3.connect(config.DB_FILE)
    try:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM proxies").fetchone()[0] == 1
    finally:
        connection.close()
