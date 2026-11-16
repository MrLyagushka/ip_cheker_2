"""Живая проверка ping: настоящий subprocess, без моков.

Пропускается, если системного ping нет. 192.0.2.1 — TEST-NET-1, он не отвечает.
"""
import asyncio
import shutil

import pytest

from utils import ping

pytestmark = pytest.mark.skipif(shutil.which("ping") is None, reason="нет системного ping")


def test_loopback_is_alive():
    assert asyncio.run(ping.ping_one("127.0.0.1")) == ("127.0.0.1", True)


def test_unroutable_is_dead():
    ip, alive = asyncio.run(ping.ping_one("192.0.2.1"))
    assert ip == "192.0.2.1"
    assert alive is False


def test_ping_many_mixed():
    results = asyncio.run(ping.ping_many(["127.0.0.1", "192.0.2.1"], limit=2))
    assert results == {"127.0.0.1": True, "192.0.2.1": False}
