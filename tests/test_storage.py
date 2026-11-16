import asyncio
import json

import config
from utils import storage


def test_init_creates_db_and_dirs(data):
    assert config.DB_FILE.exists()
    assert config.RESULTS_DIR.is_dir()
    assert config.LOG_FILE.parent.is_dir()
    assert storage.rows("SELECT name FROM sqlite_master WHERE type='table'")


def test_wal_and_full_sync(data):
    assert storage.db().execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert storage.db().execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL


def test_register_user_writes_once(data, monkeypatch):
    statements = []
    original = storage.run

    def counted(sql, params=()):
        statements.append(sql.split()[0])
        return original(sql, params)

    monkeypatch.setattr(storage, "run", counted)

    async def scenario():
        assert await storage.register_user(7, "sedov") is True
        assert await storage.register_user(7, "sedov") is False
        assert await storage.register_user(8, None) is True

    asyncio.run(scenario())
    assert statements == ["INSERT", "INSERT"]
    assert set(storage.all_users()) == {"7", "8"}


def test_init_restores_known_users(data):
    asyncio.run(storage.register_user(11, "a"))
    storage.KNOWN_USERS.clear()
    storage.init()
    assert 11 in storage.KNOWN_USERS
    assert asyncio.run(storage.register_user(11, "a")) is False


def test_history_cap_and_order(data):
    async def scenario():
        for i in range(60):
            await storage.add_history(5, {"ts": str(i), "type": "host", "target": "1.1.1.1", "up": 1, "total": 1})

    asyncio.run(scenario())
    items = storage.get_history(5)
    assert len(items) == config.HISTORY_LIMIT
    assert items[-1]["ts"] == "59"
    assert items[0]["ts"] == "10"


def test_history_is_per_user(data):
    async def scenario():
        await storage.add_history(1, {"ts": "a", "type": "host", "target": "1.1.1.1", "up": 1, "total": 1})
        await storage.add_history(2, {"ts": "b", "type": "subnet", "target": "10.0.0.0/24", "up": 3, "total": 256})

    asyncio.run(scenario())
    assert set(storage.all_history()) == {"1", "2"}
    assert storage.get_history(2)[0]["type"] == "subnet"


def test_clear_history_single_and_all(data):
    async def scenario():
        await storage.add_history(1, {"ts": "a"})
        await storage.add_history(2, {"ts": "b"})
        assert await storage.clear_history(1) == 1
        assert storage.get_history(1) == []
        assert len(storage.get_history(2)) == 1
        assert await storage.clear_history() == 1
        assert storage.all_history() == {}

    asyncio.run(scenario())


def test_tracked_add_dup_and_limit(data, monkeypatch):
    monkeypatch.setattr(config, "MAX_WATCH", 2)

    async def scenario():
        assert await storage.add_tracked(3, "1.1.1.1") == "ok"
        assert await storage.add_tracked(3, "1.1.1.1") == "dup"
        assert await storage.add_tracked(3, "2.2.2.2") == "ok"
        assert await storage.add_tracked(3, "3.3.3.3") == "limit"

    asyncio.run(scenario())
    items = storage.get_tracked(3)
    assert [item["ip"] for item in items] == ["1.1.1.1", "2.2.2.2"]
    assert all(item["status"] == "unknown" for item in items)


def test_remove_tracked_by_index_only_own_list(data):
    async def scenario():
        await storage.add_tracked(1, "1.1.1.1")
        await storage.add_tracked(1, "2.2.2.2")
        await storage.add_tracked(2, "9.9.9.9")
        assert await storage.remove_tracked(1, 0) == "1.1.1.1"
        assert await storage.remove_tracked(1, 5) is None
        assert await storage.remove_tracked(1, -1) is None

    asyncio.run(scenario())
    assert [item["ip"] for item in storage.get_tracked(1)] == ["2.2.2.2"]
    assert [item["ip"] for item in storage.get_tracked(2)] == ["9.9.9.9"]


def test_save_tracked_updates_status_and_never_resurrects(data):
    async def scenario():
        await storage.add_tracked(1, "1.1.1.1")
        snapshot = storage.all_tracked()
        await storage.remove_tracked(1, 0)          # пользователь удалил, пока шёл тик
        snapshot["1"][0]["status"] = "up"
        await storage.save_tracked(snapshot)

    asyncio.run(scenario())
    assert storage.get_tracked(1) == []             # удалённая запись не вернулась


def test_settings_merge_and_clamp(data):
    async def scenario():
        await storage.save_settings({"ping_limit": 64})
        await storage.save_settings({"proxy": "socks5://h:1"})
        assert storage.load_settings()["ping_limit"] == 64
        assert storage.load_settings()["proxy"] == "socks5://h:1"
        await storage.save_settings({"ping_limit": 9999})
        assert storage.load_settings()["ping_limit"] == config.PING_LIMIT_MAX
        await storage.save_settings({"ping_limit": "мусор"})
        assert storage.load_settings()["ping_limit"] == config.PING_LIMIT_DEFAULT

    asyncio.run(scenario())


def test_save_result_overwrites_same_file(data):
    first = storage.save_result(4, "старое")
    second = storage.save_result(4, "новое")
    assert first == second
    assert second.name == "result_4.txt"
    assert second.read_text("utf-8") == "новое"


def test_proxy_crud(data):
    record = {"id": "abc123", "owner": 5, "owner_name": "Пётр", "host": "1.2.3.4", "port": 1080,
              "login": "u1", "password": "p1", "status": "waiting", "created": storage.now(), "last_check": ""}
    storage.add_proxy(record)
    assert storage.get_proxy("abc123")["host"] == "1.2.3.4"
    storage.set_proxy_status("abc123", "up")
    assert storage.get_proxy("abc123")["status"] == "up"
    assert storage.get_proxy("abc123")["last_check"]
    assert len(storage.all_proxies()) == 1
    assert storage.remove_proxy("abc123") is True
    assert storage.get_proxy("abc123") is None
    assert storage.remove_proxy("abc123") is False


def test_migration_from_old_json(data):
    config.LEGACY_FILES["users"].write_text(json.dumps({"5": {"username": "old", "first_seen": "2024-01-01 00:00:00"}}), "utf-8")
    config.LEGACY_FILES["history"].write_text(json.dumps({"5": [{"ts": "t", "type": "host", "target": "1.1.1.1", "up": 1, "total": 1}]}), "utf-8")
    config.LEGACY_FILES["tracked"].write_text(json.dumps({"5": [{"ip": "8.8.8.8", "status": "up"}]}), "utf-8")
    config.LEGACY_FILES["settings"].write_text(json.dumps({"ping_limit": 16}), "utf-8")

    storage.init()

    assert "5" in storage.all_users()
    assert storage.get_history(5)[0]["target"] == "1.1.1.1"
    assert storage.get_tracked(5)[0]["status"] == "up"
    assert storage.load_settings()["ping_limit"] == 16
    assert config.LEGACY_FILES["users"].with_suffix(".json.migrated").exists()
    assert not config.LEGACY_FILES["users"].exists()

    storage.init()  # повторный запуск ничего не дублирует
    assert len(storage.get_history(5)) == 1
