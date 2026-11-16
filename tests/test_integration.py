"""Интеграция: настоящий Dispatcher + роутеры + middleware + FSM, фейковый Bot.

Проверяем весь путь апдейта, а не отдельные функции.
"""
import asyncio

import config
from utils import storage
from utils import ping


async def feed(dp, bot, updates):
    for update in updates:
        await dp.feed_update(bot=bot, update=update)


def patch_ping(monkeypatch, alive=True):
    async def fake_ping_many(ips, limit=32, progress=None, cancel=None):
        return {ip: alive for ip in ips}

    monkeypatch.setattr(ping, "ping_many", fake_ping_many)


def test_start_registers_user_and_shows_menu(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/start", uid=55)]))
    assert "55" in storage.all_users()
    assert "Что умею" in bot.sent[0].text
    assert bot.sent[0].reply_markup is not None


def test_scan_command_end_to_end(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [msg("/scan 8.8.8.8", uid=55)]))
    assert storage.get_history(55)[0]["target"] == "8.8.8.8"
    assert "доступен" in bot.edits[-1].text


def test_scan_via_fsm_two_messages(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [msg("/scan", uid=55), msg("8.8.8.8", uid=55, message_id=2)]))
    assert "Пришли IPv4" in bot.sent[0].text
    assert storage.get_history(55)[0]["target"] == "8.8.8.8"


def test_menu_button_then_scan_button(dp, data, bot, msg, cb, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [
        msg("/start", uid=55),
        cb("scan:start", uid=55),
        msg("1.1.1.1", uid=55, message_id=3),
    ]))
    assert storage.get_history(55)[0]["target"] == "1.1.1.1"


def test_watch_list_and_remove_by_button(dp, data, bot, msg, cb):
    asyncio.run(feed(dp, bot, [
        msg("/watch 8.8.8.8", uid=55),
        msg("/watch 1.1.1.1", uid=55, message_id=2),
        msg("/myips", uid=55, message_id=3),
        cb("mon:rm:0", uid=55),
    ]))
    assert [item["ip"] for item in storage.get_tracked(55)] == ["1.1.1.1"]
    assert any("8.8.8.8" in call.text for call in bot.sent)


def test_manual_check_does_not_change_stored_status(dp, data, bot, msg, cb, monkeypatch):
    patch_ping(monkeypatch, alive=True)
    asyncio.run(feed(dp, bot, [
        msg("/watch 8.8.8.8", uid=55),
        cb("mon:check", uid=55),
    ]))
    assert storage.get_tracked(55)[0]["status"] == "unknown"  # статус меняет только тик
    assert any("Проверка сейчас" in call.text for call in bot.edits)


def test_tree_shows_history(dp, data, bot, msg, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [msg("/scan 8.8.8.8", uid=55), msg("/tree", uid=55, message_id=2)]))
    assert "Последние сканы" in bot.sent[-1].text
    assert "8.8.8.8" in bot.sent[-1].text


def test_history_clear_requires_confirmation(dp, data, bot, msg, cb, monkeypatch):
    patch_ping(monkeypatch)
    asyncio.run(feed(dp, bot, [
        msg("/scan 8.8.8.8", uid=55),
        cb("hist:clear", uid=55),
    ]))
    assert len(storage.get_history(55)) == 1  # ещё не удалено
    asyncio.run(feed(dp, bot, [cb("hist:clear:yes", uid=55)]))
    assert storage.get_history(55) == []


def test_admin_panel_is_closed_for_others(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/admin", uid=2)]))
    assert bot.sent == []


def test_admin_can_change_ping_limit(dp, data, bot, msg, cb):
    asyncio.run(feed(dp, bot, [
        msg("/admin", uid=config.ADMIN_ID),
        cb("adm:limit", uid=config.ADMIN_ID),
        msg("64", uid=config.ADMIN_ID, message_id=3),
    ]))
    assert config.load_settings()["ping_limit"] == 64
    assert any("Лимит пингов: 64" in text for text in bot.texts())


def test_admin_limit_rejects_garbage(dp, data, bot, msg, cb):
    asyncio.run(feed(dp, bot, [
        cb("adm:limit", uid=config.ADMIN_ID),
        msg("много", uid=config.ADMIN_ID, message_id=2),
    ]))
    assert config.load_settings()["ping_limit"] == config.PING_LIMIT_DEFAULT
    assert any("Нужно число" in text for text in bot.texts())


def test_admin_broadcast_goes_to_all_users(dp, data, bot, msg, cb):
    asyncio.run(feed(dp, bot, [
        msg("/start", uid=11),
        msg("/start", uid=22),
        cb("adm:bc", uid=config.ADMIN_ID),
        msg("Всем привет <b>", uid=config.ADMIN_ID, message_id=4),
    ]))
    broadcast_texts = [call.text for call in bot.sent if call.text == "Всем привет <b>"]
    # получателей трое: 11, 22 и сам админ (он тоже зарегистрирован middleware)
    assert len(broadcast_texts) == 3
    assert any("Отправлено: 3" in call.text for call in bot.edits)


def test_callback_also_registers_user(dp, data, bot, cb):
    asyncio.run(feed(dp, bot, [cb("menu", uid=77)]))
    assert "77" in storage.all_users()


def test_help_button(dp, data, bot, cb):
    asyncio.run(feed(dp, bot, [cb("help", uid=55)]))
    assert "Что умею" in bot.edits[-1].text


def test_wiring_middleware_and_routers(dp):
    from middlewares.users import UserMiddleware

    assert any(isinstance(m, UserMiddleware) for m in dp.update.outer_middleware)
    names = [r.name for r in dp.sub_routers]
    assert names == ["start", "scan", "history", "monitor", "admin"]


def test_unwatch_shows_same_list(dp, data, bot, msg):
    asyncio.run(feed(dp, bot, [msg("/watch 8.8.8.8", uid=55), msg("/unwatch", uid=55, message_id=2)]))
    assert "8.8.8.8" in bot.sent[-1].text
    assert any(b.callback_data == "mon:rm:0" for row in bot.sent[-1].reply_markup.inline_keyboard for b in row)
