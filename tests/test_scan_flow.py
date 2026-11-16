import asyncio

import pytest

import config
from handlers import scan
from utils import storage
from utils import ping


def test_scan_host_saves_history(data, bot, monkeypatch):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        return {ip: True for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8"))

    items = storage.get_history(5)
    assert len(items) == 1
    assert items[0]["type"] == "host"
    assert items[0]["target"] == "8.8.8.8"
    assert (items[0]["up"], items[0]["total"]) == (1, 1)
    assert "доступен" in bot.edits[-1].text
    assert 5 not in scan.BUSY
    assert scan.CANCELS == {}


def test_invalid_target_is_explained(data, bot):
    asyncio.run(scan.run_scan(bot, 5, 5, "привет"))
    assert any("не похож на IPv4" in text for text in bot.texts())
    assert storage.get_history(5) == []
    assert scan.BUSY == set()


def test_subnet_scan_writes_file_and_document(data, bot, monkeypatch):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        assert len(ips) == 256
        if progress:
            await progress(10, 256)
        return {ip: index % 2 == 0 for index, ip in enumerate(ips)}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    asyncio.run(scan.run_scan(bot, 5, 5, "192.168.0.0"))

    assert len(bot.documents) == 1
    path = config.RESULTS_DIR / "result_5.txt"
    assert path.exists()
    assert len(path.read_text("utf-8").strip().splitlines()) == 258  # заголовок + пустая + 256
    assert any("Проверено 10/256" in call.text for call in bot.edits)

    item = storage.get_history(5)[0]
    assert item["type"] == "subnet"
    assert item["target"] == "192.168.0.0/24"
    assert (item["up"], item["total"]) == (128, 256)


def test_second_scan_is_rejected(data, bot, monkeypatch):
    async def fake_ping_many(ips, **kwargs):
        return {ip: True for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    scan.BUSY.add(7)
    asyncio.run(scan.run_scan(bot, 7, 7, "8.8.8.8"))
    assert any("уже идёт сканирование" in text for text in bot.texts())
    assert storage.get_history(7) == []


def test_busy_is_released_even_if_ping_crashes(data, bot, monkeypatch):
    async def broken(ips, **kwargs):
        raise RuntimeError("подпроцессы кончились")

    monkeypatch.setattr(ping, "ping_many", broken)
    with pytest.raises(RuntimeError):
        asyncio.run(scan.run_scan(bot, 9, 9, "8.8.8.8"))
    assert scan.BUSY == set()
    assert scan.CANCELS == {}


def test_cancelled_scan_reports_partial(data, bot, monkeypatch):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        cancel.set()  # пользователь нажал «Отмена»
        return {ips[0]: True, ips[1]: False}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    asyncio.run(scan.run_scan(bot, 5, 5, "10.0.0.0"))
    assert "Отменено" in bot.edits[-1].text
    assert storage.get_history(5)[0]["total"] == 2


def test_scan_uses_current_ping_limit(data, bot, monkeypatch):
    seen = {}

    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        seen["limit"] = limit
        return {ip: True for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    asyncio.run(storage.save_settings({"ping_limit": 7}))
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8"))
    assert seen["limit"] == 7  # новый лимит применился без всякого resize()
