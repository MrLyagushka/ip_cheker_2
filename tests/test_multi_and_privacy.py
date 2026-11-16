"""Новые требования: несколько адресов в /scan и /watch, пароль прокси только в личке."""
import asyncio

import config
from handlers import scan
from utils import ping, storage


def patch_ping(monkeypatch, alive=True):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        return {ip: alive for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)


async def feed(dp, bot, updates):
    for update in updates:
        await dp.feed_update(bot=bot, update=update)


# --- 3. скан нескольких адресов -------------------------------------------

def test_scan_two_ips(data, bot, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8 1.1.1.1"))
    item = storage.get_history(5)[0]
    assert item["type"] == "multi"
    assert item["target"] == "8.8.8.8, 1.1.1.1"
    assert (item["up"], item["total"]) == (2, 2)
    assert "8.8.8.8" in bot.edits[-1].text and "1.1.1.1" in bot.edits[-1].text
    assert len(bot.documents) == 1                      # список адресов -> файл с результатом


def test_scan_mixed_subnet_and_ip(data, bot, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8 10.0.0.0"))
    item = storage.get_history(5)[0]
    assert item["total"] == 257
    assert item["type"] == "multi"


def test_scan_command_with_spaces(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [msg("/scan 8.8.8.8 1.1.1.1 9.9.9.9", uid=55)]))
    assert storage.get_history(55)[0]["total"] == 3


def test_scan_bad_token_in_list(data, bot):
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8 мусор"))
    assert "мусор" in bot.texts()[-1]
    assert storage.get_history(5) == []


def test_scan_too_many_addresses(data, bot, monkeypatch):
    monkeypatch.setattr(config, "SCAN_MAX_IPS", 10)
    asyncio.run(scan.run_scan(bot, 5, 5, "10.0.0.0"))
    assert "Лимит" in bot.texts()[-1]
    assert storage.get_history(5) == []


# --- 4. /watch нескольких адресов -----------------------------------------

def test_watch_multiple_ips(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/watch 8.8.8.8 1.1.1.1 9.9.9.9", uid=55)]))
    assert [item["ip"] for item in storage.get_tracked(55)] == ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
    assert "Добавлены" in bot.sent[-1].text


def test_watch_reports_duplicates_and_garbage(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [
        msg("/watch 8.8.8.8", uid=55),
        msg("/watch 8.8.8.8 1.1.1.1 мусор", uid=55, message_id=2),
    ]))
    body = bot.sent[-1].text
    assert "Уже были" in body and "8.8.8.8" in body
    assert "Не добавлены" in body and "мусор" in body
    assert [item["ip"] for item in storage.get_tracked(55)] == ["8.8.8.8", "1.1.1.1"]


def test_watch_stops_at_limit(dp, data, bot, msg, monkeypatch):
    monkeypatch.setattr(config, "MAX_WATCH", 2)
    asyncio.run(feed(dp, bot, [msg("/watch 1.1.1.1 2.2.2.2 3.3.3.3 4.4.4.4", uid=55)]))
    assert len(storage.get_tracked(55)) == 2
    assert "лимит" in bot.sent[-1].text


def test_watch_via_fsm_multiple(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/watch", uid=55), msg("8.8.8.8 1.1.1.1", uid=55, message_id=2)]))
    assert len(storage.get_tracked(55)) == 2


# --- 1. пароль прокси не показываем в группе ------------------------------

def test_get_proxy_in_group_has_no_password(dp, data, bot, msg):
    update = msg("/get_proxy", uid=55, chat_id=-1001234567890, chat_type="supergroup", thread_id=77)
    asyncio.run(feed(dp, bot, [update]))
    body = bot.sent[0].text
    assert "docker run" not in body
    assert "PROXY_PASSWORD" not in body
    assert "личны" in body.lower()
    button = bot.sent[0].reply_markup.inline_keyboard[0][0]
    assert button.url == "https://t.me/test_bot?start=get_proxy"
    assert bot.sent[0].message_thread_id == 77          # ответ в той же теме
    assert storage.all_proxies() == []


def test_get_proxy_with_ip_in_group_also_hidden(dp, data, bot, msg):
    update = msg("/get_proxy 1.2.3.4", uid=55, chat_id=-1001234567890, chat_type="supergroup")
    asyncio.run(feed(dp, bot, [update]))
    assert "PROXY_PASSWORD" not in bot.sent[0].text
    assert storage.all_proxies() == []


def test_proxy_button_in_group_has_no_password(dp, data, bot, cb):
    update = cb("px:new", uid=55, chat_id=-1001234567890, chat_type="supergroup")
    asyncio.run(feed(dp, bot, [update]))
    assert "PROXY_PASSWORD" not in bot.sent[0].text
    assert bot.sent[0].reply_markup.inline_keyboard[0][0].url.startswith("https://t.me/")


def test_deep_link_issues_command_in_private(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/start get_proxy", uid=55)]))
    assert "PROXY_PASSWORD=" in bot.sent[0].text        # в личке пароль можно
    assert "docker run" in bot.sent[0].text


def test_private_get_proxy_still_works(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/get_proxy", uid=55), msg("1.2.3.4", uid=55, message_id=2)]))
    assert storage.all_proxies()[0]["host"] == "1.2.3.4"


# --- 2. правильный формат адреса прокси -----------------------------------

def test_bad_host_keeps_state_and_allows_retry(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [
        msg("/get_proxy", uid=55),
        msg("162.35.229.164:abc", uid=55, message_id=2),
    ]))
    assert "Порт" in bot.sent[-1].text
    assert "Формат:" in bot.sent[-1].text
    assert storage.all_proxies() == []
    asyncio.run(feed(dp, bot, [msg("162.35.229.164", uid=55, message_id=3)]))
    assert storage.all_proxies()[0]["host"] == "162.35.229.164"   # повтор без /get_proxy заново


def test_host_with_port_is_accepted(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/get_proxy", uid=55), msg("1.2.3.4:9050", uid=55, message_id=2)]))
    record = storage.all_proxies()[0]
    assert (record["host"], record["port"]) == ("1.2.3.4", 9050)


def test_format_hint_is_shown_upfront(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/get_proxy", uid=55)]))
    assert "162.35.229.164:1080" in bot.sent[0].text


def test_cancel_exits_proxy_input(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [
        msg("/get_proxy", uid=55),
        msg("/cancel", uid=55, message_id=2),
        msg("1.2.3.4", uid=55, message_id=3),
    ]))
    assert storage.all_proxies() == []
    assert "Отменил" in bot.sent[-1].text  # голое IP после отмены уже никто не ловит


def test_cancel_exits_scan_input(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/scan", uid=55), msg("/cancel", uid=55, message_id=2)]))
    assert "Отменил" in bot.sent[-1].text
    assert storage.get_history(55) == []
