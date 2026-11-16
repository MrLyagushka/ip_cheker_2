"""Генерация доступа участнику и честная проверка прокси-туннеля."""
import asyncio

import config
from utils import proxies


class FakeResponse:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    def __init__(self, status=200, error=None):
        self.status = status
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        if self.error:
            raise self.error
        return FakeResponse(self.status)


def patch_http(monkeypatch, status=200, error=None):
    monkeypatch.setattr(proxies.aiohttp, "ClientSession", lambda **kwargs: FakeSession(status, error))
    monkeypatch.setattr(proxies.ProxyConnector, "from_url", classmethod(lambda cls, url, **kw: None))


def test_credentials_are_random_and_shell_safe():
    first = proxies.new_credentials()
    second = proxies.new_credentials()
    assert first != second
    login, password = first
    assert login.startswith("u") and len(login) == 7
    assert len(password) == 24
    assert all(char.isalnum() for char in login + password)  # никаких кавычек и $ в docker-команде


def test_docker_command_format():
    command = proxies.docker_command("uabc123", "deadbeef")
    assert command == (
        "docker run -d --name socks5 --restart always -p 1080:1080 "
        "-e PROXY_USER=uabc123 -e PROXY_PASSWORD=deadbeef serjs/go-socks5-proxy"
    )


def test_docker_command_custom_port(monkeypatch):
    monkeypatch.setattr(config, "PROXY_PORT", 9050)
    assert "-p 9050:9050" in proxies.docker_command("u1", "p1")


def test_record_and_url():
    record = proxies.new_record(5, "Пётр", "1.2.3.4", "uabc", "secret")
    assert record["owner"] == 5
    assert record["status"] == "waiting"
    assert record["port"] == config.PROXY_PORT
    assert proxies.url(record) == f"socks5://uabc:secret@1.2.3.4:{config.PROXY_PORT}"


def test_check_accepts_any_http_answer(monkeypatch):
    patch_http(monkeypatch, status=401)  # Telegram ответил «Unauthorized» — туннель работает
    assert asyncio.run(proxies.check("socks5://u:p@1.2.3.4:1080")) is True


def test_check_false_on_connection_error(monkeypatch):
    patch_http(monkeypatch, error=OSError("Couldn't connect to proxy"))
    assert asyncio.run(proxies.check("socks5://u:p@1.2.3.4:1080")) is False


def test_check_direct(monkeypatch):
    patch_http(monkeypatch, status=302)
    assert asyncio.run(proxies.check_direct()) is True
    patch_http(monkeypatch, error=OSError("no route"))
    assert asyncio.run(proxies.check_direct()) is False


def test_check_many_respects_limit(monkeypatch):
    active = peak = 0

    async def fake_check(url, timeout=10):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return True

    monkeypatch.setattr(proxies, "check", fake_check)
    urls = {str(i): f"socks5://h:{i}" for i in range(12)}
    results = asyncio.run(proxies.check_many(urls, limit=3))
    assert len(results) == 12 and all(results.values())
    assert peak <= 3


def test_password_never_leaks_in_texts():
    from utils import text

    record = proxies.new_record(5, "Пётр", "1.2.3.4", "uabc", "SuperSecret")
    assert "SuperSecret" not in text.mask_proxy(proxies.url(record))
    assert "SuperSecret" not in text.proxies_text([record], is_admin=True)
