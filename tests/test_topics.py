"""Супергруппа с темами (topics): алерты в нужную тему и ответы в ту же тему."""
import asyncio

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

import config
from handlers import scan
from utils import ping, sender, storage, watcher

GROUP = -1001234567890
TOPIC = 77


def make_change(track):
    track({"1": [("1.1.1.1", "up")]})


def patch_ping(monkeypatch, alive=False):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        return {ip: alive for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)


def test_thread_id_from_env():
    assert config.ALERT_THREAD_ID == TOPIC


def test_alert_goes_to_topic(data, bot, monkeypatch, track):
    make_change(track)
    patch_ping(monkeypatch)
    asyncio.run(watcher.tick(bot))
    assert len(bot.sent) == 1
    assert bot.sent[0].chat_id == config.ALERT_CHAT_ID
    assert bot.sent[0].message_thread_id == TOPIC


def test_no_topic_configured_sends_plain(data, bot, monkeypatch, track):
    monkeypatch.setattr(config, "ALERT_THREAD_ID", 0)
    make_change(track)
    patch_ping(monkeypatch)
    asyncio.run(watcher.tick(bot))
    assert len(bot.sent) == 1
    assert bot.sent[0].message_thread_id is None


def test_closed_topic_falls_back_to_general(data, make_bot, monkeypatch, sleeps, track):
    bot = make_bot({"SendMessage": [
        TelegramBadRequest(method=SendMessage(chat_id=GROUP, text="x"),
                           message="Bad Request: message thread not found"),
        None,
    ]})
    make_change(track)
    patch_ping(monkeypatch)
    asyncio.run(watcher.tick(bot))
    assert len(bot.sent) == 2
    assert bot.sent[0].message_thread_id == TOPIC   # сначала пробовали тему
    assert bot.sent[1].message_thread_id is None    # затем General, алерт не потерян


def test_successful_topic_send_is_not_duplicated(data, bot, monkeypatch, track):
    make_change(track)
    patch_ping(monkeypatch)
    asyncio.run(watcher.tick(bot))
    assert len(bot.sent) == 1  # запасной вариант не срабатывает без причины


def test_thread_kwargs_helper(msg):
    in_topic = msg("/id", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC).message
    private = msg("/id", uid=5).message
    assert sender.thread_kwargs(in_topic) == {"message_thread_id": TOPIC}
    assert sender.thread_kwargs(private) == {}
    assert sender.thread_kwargs(None) == {}


def test_id_command_in_topic(dp, data, bot, msg):
    update = msg("/id", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC)
    asyncio.run(dp.feed_update(bot=bot, update=update))
    assert f"chat_id: {GROUP}" in bot.sent[0].text
    assert f"id темы: {TOPIC}" in bot.sent[0].text
    assert bot.sent[0].message_thread_id == TOPIC  # ответ пришёл в ту же тему


def test_id_command_in_private(dp, data, bot, msg):
    asyncio.run(dp.feed_update(bot=bot, update=msg("/id", uid=5)))
    assert "нет (General или личный чат)" in bot.sent[0].text
    assert bot.sent[0].message_thread_id is None


def test_scan_in_topic_replies_in_same_topic(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch, alive=True)
    update = msg("/scan 8.8.8.8", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC)
    asyncio.run(dp.feed_update(bot=bot, update=update))
    assert bot.sent[0].message_thread_id == TOPIC
    assert storage.get_history(5)[0]["target"] == "8.8.8.8"


def test_subnet_document_in_topic(dp, data, bot, msg, monkeypatch):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        return {ip: True for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)
    update = msg("/scan 10.0.0.0", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC)
    asyncio.run(dp.feed_update(bot=bot, update=update))
    assert bot.documents[0].message_thread_id == TOPIC


def test_watch_and_list_in_topic(dp, data, bot, msg):
    async def feed(updates):
        for update in updates:
            await dp.feed_update(bot=bot, update=update)

    asyncio.run(feed([
        msg("/watch 8.8.8.8", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC),
        msg("/myips", uid=5, chat_id=GROUP, chat_type="supergroup", thread_id=TOPIC, message_id=2),
    ]))
    assert all(call.message_thread_id == TOPIC for call in bot.sent)


def test_private_chat_has_no_thread(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch, alive=True)
    asyncio.run(dp.feed_update(bot=bot, update=msg("/scan 8.8.8.8", uid=5)))
    assert bot.sent[0].message_thread_id is None


def test_scan_thread_argument_is_optional(data, bot, monkeypatch, track):
    patch_ping(monkeypatch, alive=True)
    asyncio.run(scan.run_scan(bot, 5, 5, "8.8.8.8"))  # вызов без темы тоже работает
    assert bot.sent[0].message_thread_id is None
