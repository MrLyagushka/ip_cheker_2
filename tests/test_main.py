import asyncio

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

import config
import main as app
from utils import ping, storage


def test_no_token_stops_immediately(monkeypatch):
    monkeypatch.setattr(config, "TOKEN", "")
    with pytest.raises(SystemExit):
        app.build_bot()


def test_bot_uses_html_parse_mode(monkeypatch):
    monkeypatch.setattr(config, "TOKEN", "42:TEST")
    bot = app.build_bot()
    assert isinstance(bot, Bot)
    assert bot.default.parse_mode == "HTML"


def test_proxy_goes_only_to_telegram_session(data, monkeypatch):
    monkeypatch.setattr(config, "TOKEN", "42:TEST")
    asyncio.run(storage.save_settings({"proxy": "socks5://user:pass@127.0.0.1:1080"}))
    bot = app.build_bot()
    assert isinstance(bot.session, AiohttpSession)
    # ping про прокси не знает вообще: в команде только флаги и адрес
    assert "socks5" not in " ".join(ping.build_cmd("1.1.1.1"))


def test_dispatcher_type(dp):
    assert isinstance(dp, Dispatcher)


def test_polling_recovers_after_crash(monkeypatch):
    """Мёртвый прокси не должен убивать бота: polling перезапускается."""
    import main as app
    from utils import proxy_watch

    attempts = []
    recovered = []

    class FakeDispatcher:
        async def start_polling(self, bot):
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("Cannot connect to proxy")

    async def fake_recover(bot):
        recovered.append(1)
        return True

    async def fake_sleep(delay):
        return None

    monkeypatch.setattr(proxy_watch, "try_recover", fake_recover)
    monkeypatch.setattr(app.asyncio, "sleep", fake_sleep)
    asyncio.run(app.run_polling(FakeDispatcher(), bot=None))
    assert len(attempts) == 3
    assert len(recovered) == 2


def test_polling_stops_cleanly(monkeypatch):
    import main as app

    class FakeDispatcher:
        async def start_polling(self, bot):
            return None                      # SIGTERM: штатный выход

    asyncio.run(app.run_polling(FakeDispatcher(), bot=None))
