import asyncio

import config
from utils import ping, storage, watcher


def patch_ping(monkeypatch, results):
    calls = []

    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        calls.append(list(ips))
        return {ip: results.get(ip, False) for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    return calls


def test_tick_without_ips_does_nothing(data, bot, monkeypatch, track):
    calls = patch_ping(monkeypatch, {})
    assert asyncio.run(watcher.tick(bot)) == {}
    assert calls == []
    assert bot.sent == []


def test_first_observation_is_silent(data, bot, monkeypatch, track):
    track({"1": [("1.1.1.1", "unknown")]})
    patch_ping(monkeypatch, {"1.1.1.1": True})
    assert asyncio.run(watcher.tick(bot)) == {}
    assert bot.sent == []
    assert storage.get_tracked(1)[0]["status"] == "up"


def test_status_change_goes_to_group(data, bot, monkeypatch, track):
    track({"1": [("1.1.1.1", "up")]})
    patch_ping(monkeypatch, {"1.1.1.1": False})
    changes = asyncio.run(watcher.tick(bot))
    assert changes == {"1.1.1.1": ("up", "down")}
    assert len(bot.sent) == 1
    assert bot.sent[0].chat_id == config.ALERT_CHAT_ID
    assert "up → down" in bot.sent[0].text
    assert storage.get_tracked(1)[0]["status"] == "down"


def test_stable_status_is_silent(data, bot, monkeypatch, track):
    track({"1": [("1.1.1.1", "up")]})
    patch_ping(monkeypatch, {"1.1.1.1": True})
    assert asyncio.run(watcher.tick(bot)) == {}
    assert bot.sent == []


def test_shared_ip_pings_once_and_alerts_once(data, bot, monkeypatch, track):
    track({"1": [("1.1.1.1", "up")], "2": [("1.1.1.1", "up"), ("2.2.2.2", "down")]})
    calls = patch_ping(monkeypatch, {"1.1.1.1": False, "2.2.2.2": True})
    changes = asyncio.run(watcher.tick(bot))
    assert calls == [["1.1.1.1", "2.2.2.2"]]  # дедупликация: один пинг на адрес
    assert set(changes) == {"1.1.1.1", "2.2.2.2"}
    assert len(bot.sent) == 1  # одно сообщение в группу на все изменения
    assert storage.get_tracked(2)[1]["status"] == "up"


def test_broken_user_does_not_break_others(data, bot, monkeypatch, track):
    track({"1": [("1.1.1.1", "up")]})
    storage.run("INSERT INTO tracked(uid, ip, status) VALUES(2, NULL, 'up')")  # битая запись
    patch_ping(monkeypatch, {"1.1.1.1": False})
    changes = asyncio.run(watcher.tick(bot))
    assert changes == {"1.1.1.1": ("up", "down")}
    assert storage.get_tracked(1)[0]["status"] == "down"


def test_no_alert_chat_configured(data, bot, monkeypatch, track):
    monkeypatch.setattr(config, "ALERT_CHAT_ID", 0)
    track({"1": [("1.1.1.1", "up")]})
    patch_ping(monkeypatch, {"1.1.1.1": False})
    assert asyncio.run(watcher.tick(bot)) == {"1.1.1.1": ("up", "down")}
    assert bot.sent == []
    assert storage.get_tracked(1)[0]["status"] == "down"


def test_loop_survives_broken_tick(monkeypatch):
    monkeypatch.setattr(config, "CHECK_INTERVAL", 3600)
    ticks = []

    async def broken_tick(bot):
        ticks.append(len(ticks))
        if len(ticks) == 1:
            raise RuntimeError("упал")
        return {}

    async def stop_sleep(delay):
        if len(ticks) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(watcher, "tick", broken_tick)
    monkeypatch.setattr(watcher.asyncio, "sleep", stop_sleep)
    try:
        asyncio.run(watcher.watch_loop(bot=None))
    except asyncio.CancelledError:
        pass
    assert len(ticks) == 3  # после падения цикл продолжил работать
