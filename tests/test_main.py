import asyncio

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

import config
import main as app
from utils import storage
from utils import ping


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
