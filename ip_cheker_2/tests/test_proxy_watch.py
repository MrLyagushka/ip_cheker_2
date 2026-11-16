"""Жизненный цикл прокси участника: ожидание, успех, падение с тэгом, авто-переключение."""
import asyncio
from datetime import datetime, timedelta

import config
from utils import proxies, proxy_watch, storage


def add_proxy(owner=5, host="1.2.3.4", status="waiting", age_hours=0, name="Пётр"):
    record = proxies.new_record(owner, name, host, "uabc", "secret")
    record["status"] = status
    record["created"] = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%d %H:%M:%S")
    storage.add_proxy(record)
    return record


def patch_checks(monkeypatch, alive_ids=(), direct=True, main_alive=False):
    async def fake_check_many(urls, limit=5):
        return {key: key in alive_ids for key in urls}

    async def fake_check(url, timeout=10):
        return main_alive

    async def fake_direct(timeout=10):
        return direct

    monkeypatch.setattr(proxies, "check_many", fake_check_many)
    monkeypatch.setattr(proxies, "check", fake_check)
    monkeypatch.setattr(proxies, "check_direct", fake_direct)


def test_next_status_matrix():
    now = storage.now()
    old = (datetime.now() - timedelta(hours=config.PROXY_WAIT_HOURS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    assert proxy_watch.next_status("waiting", True, now) == "up"
    assert proxy_watch.next_status("waiting", False, now) == "waiting"
    assert proxy_watch.next_status("waiting", False, old) == "expired"
    assert proxy_watch.next_status("up", False, now) == "down"
    assert proxy_watch.next_status("down", True, now) == "up"
    assert proxy_watch.next_status("down", False, now) == "down"
    assert proxy_watch.next_status("expired", False, old) == "expired"
    assert proxy_watch.next_status("expired", True, old) == "up"


def test_waiting_then_success_notifies_owner(data, bot, monkeypatch):
    record = add_proxy()
    patch_checks(monkeypatch, alive_ids=[record["id"]])
    changes = asyncio.run(proxy_watch.tick(bot))
    assert changes == {record["id"]: ("waiting", "up")}
    assert len(bot.sent) == 1
    message = bot.sent[0]
    assert message.chat_id == config.ALERT_CHAT_ID
    assert message.message_thread_id == config.ALERT_THREAD_ID
    assert 'tg://user?id=5' in message.text          # владельца тэгнули
    assert "запущен и работает" in message.text
    assert storage.get_proxy(record["id"])["status"] == "up"


def test_fallen_proxy_tags_owner(data, bot, monkeypatch):
    record = add_proxy(status="up")
    patch_checks(monkeypatch, alive_ids=[], direct=True)
    changes = asyncio.run(proxy_watch.tick(bot))
    assert changes == {record["id"]: ("up", "down")}
    assert "перестал отвечать" in bot.sent[0].text
    assert "tg://user?id=5" in bot.sent[0].text
    assert "docker logs socks5" in bot.sent[0].text     # подсказка, что делать


def test_recovery_notifies(data, bot, monkeypatch):
    record = add_proxy(status="down")
    patch_checks(monkeypatch, alive_ids=[record["id"]])
    asyncio.run(proxy_watch.tick(bot))
    assert "снова в строю" in bot.sent[0].text


def test_stable_proxy_is_silent(data, bot, monkeypatch):
    record = add_proxy(status="up")
    patch_checks(monkeypatch, alive_ids=[record["id"]])
    assert asyncio.run(proxy_watch.tick(bot)) == {}
    assert bot.sent == []


def test_waiting_expires(data, bot, monkeypatch):
    record = add_proxy(age_hours=config.PROXY_WAIT_HOURS + 1)
    patch_checks(monkeypatch, alive_ids=[])
    changes = asyncio.run(proxy_watch.tick(bot))
    assert changes == {record["id"]: ("waiting", "expired")}
    assert "Заявка снята" in bot.sent[0].text


def test_no_proxies_no_work(data, bot, monkeypatch):
    patch_checks(monkeypatch)
    assert asyncio.run(proxy_watch.tick(bot)) == {}
    assert bot.sent == []


def test_failover_switches_to_live_community_proxy(data, bot, monkeypatch):
    record = add_proxy(status="up")
    asyncio.run(storage.save_settings({"proxy": "socks5://dead:1080"}))
    patch_checks(monkeypatch, alive_ids=[record["id"]], direct=False, main_alive=False)
    old_session = bot.session

    switched = asyncio.run(proxy_watch.failover(bot, storage.all_proxies(), {record["id"]: True}))

    assert switched == record["id"]
    assert bot.session is not old_session                       # сессия реально заменена
    assert storage.load_settings()["proxy"] == proxies.url(record)
    assert "работаю через прокси" in bot.sent[-1].text
    assert "secret" not in bot.sent[-1].text                    # пароль не утёк в чат


def test_no_failover_when_current_path_works(data, bot, monkeypatch):
    record = add_proxy(status="up")
    asyncio.run(storage.save_settings({"proxy": "socks5://live:1080"}))

    async def fake_check(url, timeout=10):
        return True

    monkeypatch.setattr(proxies, "check", fake_check)
    old_session = bot.session
    assert asyncio.run(proxy_watch.failover(bot, storage.all_proxies(), {record["id"]: True})) is None
    assert bot.session is old_session
    assert bot.sent == []


def test_returns_to_main_proxy_when_it_recovers(data, bot, monkeypatch):
    record = add_proxy(status="up")
    asyncio.run(storage.save_settings({"proxy": proxies.url(record)}))
    monkeypatch.setattr(config, "PROXY_URL", "socks5://main:1080")
    patch_checks(monkeypatch, alive_ids=[record["id"]], main_alive=True)

    assert asyncio.run(proxy_watch.failover(bot, storage.all_proxies(), {record["id"]: True})) == "main"
    assert storage.load_settings()["proxy"] == "socks5://main:1080"
    assert "вернулся на него" in bot.sent[-1].text


def test_no_switch_when_nothing_alive(data, bot, monkeypatch):
    add_proxy(status="down")
    asyncio.run(storage.save_settings({"proxy": "socks5://dead:1080"}))
    patch_checks(monkeypatch, alive_ids=[], direct=False, main_alive=False)
    old_session = bot.session
    assert asyncio.run(proxy_watch.failover(bot, storage.all_proxies(), {})) is None
    assert bot.session is old_session


def test_direct_connection_is_not_replaced(data, bot, monkeypatch):
    record = add_proxy(status="up")
    patch_checks(monkeypatch, alive_ids=[record["id"]], direct=True)
    old_session = bot.session
    assert asyncio.run(proxy_watch.failover(bot, storage.all_proxies(), {record["id"]: True})) is None
    assert bot.session is old_session


def test_loop_survives_broken_tick(monkeypatch):
    calls = []

    async def broken(bot):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("сеть моргнула")
        return {}

    async def stop_sleep(delay):
        if len(calls) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(proxy_watch, "tick", broken)
    monkeypatch.setattr(proxy_watch.asyncio, "sleep", stop_sleep)
    try:
        asyncio.run(proxy_watch.proxy_loop(bot=None))
    except asyncio.CancelledError:
        pass
    assert len(calls) == 3


def test_try_recover_reports_result(data, bot, monkeypatch):
    record = add_proxy(status="up")
    patch_checks(monkeypatch, alive_ids=[record["id"]], direct=False)

    async def telegram_ok(bot):
        return True, "Telegram доступен"

    from utils import selfcheck
    monkeypatch.setattr(selfcheck, "check_telegram", telegram_ok)
    assert asyncio.run(proxy_watch.try_recover(bot)) is True
    assert storage.load_settings()["proxy"] == proxies.url(record)


def test_tick_skips_network_when_no_proxies(data, bot, monkeypatch):
    called = []

    async def spy(*args, **kwargs):
        called.append(1)
        return True

    monkeypatch.setattr(proxies, "check_direct", spy)
    monkeypatch.setattr(proxies, "check", spy)
    assert asyncio.run(proxy_watch.tick(bot)) == {}
    assert called == []          # лишний трафик ни к Telegram, ни к прокси
