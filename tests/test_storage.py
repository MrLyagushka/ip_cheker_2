import asyncio
import json

import config
from utils import storage


def test_init_creates_files_and_dirs(data):
    assert config.USERS_FILE.exists()
    assert config.HISTORY_FILE.exists()
    assert config.TRACKED_FILE.exists()
    assert config.SETTINGS_FILE.exists()
    assert config.RESULTS_DIR.is_dir()
    assert config.LOG_FILE.parent.is_dir()


def test_write_json_is_atomic_and_leaves_no_tmp(data):
    path = data / "x.json"
    asyncio.run(storage.write_json(path, {"a": 1}))
    assert json.loads(path.read_text("utf-8")) == {"a": 1}
    assert not (data / "x.json.tmp").exists()


def test_read_json_broken_returns_default(data):
    path = data / "bad.json"
    path.write_text("{oops", "utf-8")
    assert storage.read_json(path, {"default": True}) == {"default": True}
    assert storage.read_json(data / "missing.json", []) == []


def test_register_user_writes_once(data, monkeypatch):
    writes = []
    original = storage.write_json

    async def counted(path, payload):
        writes.append(path.name)
        await original(path, payload)

    monkeypatch.setattr(storage, "write_json", counted)

    async def scenario():
        assert await storage.register_user(7, "sedov") is True
        assert await storage.register_user(7, "sedov") is False
        assert await storage.register_user(8, None) is True

    asyncio.run(scenario())
    assert writes == ["users.json", "users.json"]
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


def test_clear_history_single_and_all(data):
    async def scenario():
        await storage.add_history(1, {"ts": "a"})
        await storage.add_history(2, {"ts": "b"})
        assert await storage.clear_history(1) == 1
        assert storage.get_history(1) == []
        assert len(storage.get_history(2)) == 1
        assert await storage.clear_history() == 1
        assert storage.read_json(config.HISTORY_FILE, {}) == {}

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


def test_save_result_overwrites_same_file(data):
    first = storage.save_result(4, "старое")
    second = storage.save_result(4, "новое")
    assert first == second
    assert second.name == "result_4.txt"
    assert second.read_text("utf-8") == "новое"


def test_save_settings_merges(data):
    async def scenario():
        await storage.save_settings({"ping_limit": 64})
        await storage.save_settings({"proxy": "socks5://h:1"})

    asyncio.run(scenario())
    settings = config.load_settings()
    assert settings["ping_limit"] == 64
    assert settings["proxy"] == "socks5://h:1"
