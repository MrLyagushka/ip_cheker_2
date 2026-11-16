"""Самопроверка окружения: ICMP в контейнере и связь с Telegram через прокси."""
import asyncio

import pytest

from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.methods import GetMe

import main as app
from utils import selfcheck


class FakeProc:
    def __init__(self, returncode=0, out=b""):
        self.returncode = returncode
        self._out = out

    async def communicate(self):
        return self._out, None


def patch_exec(monkeypatch, proc):
    async def fake_exec(*cmd, **kwargs):
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr(selfcheck.asyncio, "create_subprocess_exec", fake_exec)


def test_missing_ping_binary(monkeypatch):
    monkeypatch.setattr(selfcheck.shutil, "which", lambda name: None)
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is False
    assert "iputils-ping" in detail


def test_ping_ok(monkeypatch):
    patch_exec(monkeypatch, FakeProc(0, b"1 packets transmitted, 1 received"))
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is True
    assert "ICMP работает" in detail


def test_permission_error_gives_docker_instructions(monkeypatch):
    patch_exec(monkeypatch, FakeProc(2, b"ping: socket: Operation not permitted"))
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is False
    assert "ping_group_range" in detail
    assert "NET_RAW" in detail


def test_code_two_without_text_is_still_environment_error(monkeypatch):
    patch_exec(monkeypatch, FakeProc(2, b""))
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is False
    assert "ping_group_range" in detail


def test_no_answer_is_not_permission_problem(monkeypatch):
    patch_exec(monkeypatch, FakeProc(1, b"1 packets transmitted, 0 received"))
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is False
    assert "не ответил" in detail
    assert "ping_group_range" not in detail


def test_subprocess_crash(monkeypatch):
    patch_exec(monkeypatch, OSError("exec format error"))
    ok, detail = asyncio.run(selfcheck.check_ping())
    assert ok is False
    assert "не запустился" in detail


def test_telegram_ok(bot):
    ok, detail = asyncio.run(selfcheck.check_telegram(bot))
    assert ok is True
    assert "@test_bot" in detail


def test_telegram_failure_gives_proxy_instructions(make_bot):
    bot = make_bot({"GetMe": [RuntimeError("Cannot connect to host 127.0.0.1:1080")]})
    ok, detail = asyncio.run(selfcheck.check_telegram(bot))
    assert ok is False
    assert "host.docker.internal" in detail
    assert "socks5h" in detail          # предупреждение про неподдерживаемую схему
    assert "HTTPS_PROXY" in detail      # и про игнорируемые переменные окружения


def test_bad_token_is_not_blamed_on_proxy(make_bot):
    bot = make_bot({"GetMe": [TelegramUnauthorizedError(method=GetMe(), message="Unauthorized")]})
    ok, detail = asyncio.run(selfcheck.check_telegram(bot))
    assert ok is False
    assert "Токен не принят" in detail
    assert "host.docker.internal" not in detail  # не путаем пользователя


def test_preflight_stops_bot_without_icmp(bot, monkeypatch):
    async def broken():
        return False, "ICMP запрещён"

    monkeypatch.setattr(selfcheck, "check_ping", broken)
    with pytest.raises(SystemExit) as exc:
        asyncio.run(app.preflight(bot))
    assert exc.value.code == 2


def test_preflight_tolerates_telegram_outage(bot, monkeypatch):
    async def ping_ok():
        return True, "ICMP работает"

    async def telegram_down(bot):
        return False, "прокси недоступен"

    monkeypatch.setattr(selfcheck, "check_ping", ping_ok)
    monkeypatch.setattr(selfcheck, "check_telegram", telegram_down)
    asyncio.run(app.preflight(bot))  # не должно бросать: polling повторит сам


def test_run_without_bot_skips_telegram(monkeypatch, capsys):
    async def ping_ok():
        return True, "ICMP работает"

    monkeypatch.setattr(selfcheck, "check_ping", ping_ok)
    assert asyncio.run(selfcheck.run(None)) is True
    assert "ПРОПУСК" in capsys.readouterr().out
