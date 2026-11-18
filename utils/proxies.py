"""Прокси участников: доступ, команда запуска, честная проверка туннеля.

Проверяем не «открыт ли порт», а весь путь: SOCKS5 + авторизация + TLS до
api.telegram.org. Только такой прокси реально годится для бота.
"""
from __future__ import annotations

import asyncio
import logging
import secrets

import aiohttp
from aiohttp_socks import ProxyConnector

import config
from utils import storage, text

log = logging.getLogger(__name__)

CHECK_URL = "https://api.telegram.org/"
CHECK_TIMEOUT = 10

# [NEW] Защита от «дребезга» сети:
# Прокси считается мёртвым (возвращает False) только после FAIL_THRESHOLD неудач подряд.
FAIL_THRESHOLD = 3
_fail_counts: dict[str, int] = {}


def new_credentials() -> tuple[str, str]:
    """Логин и пароль для контейнера участника. Криптостойкие, не угадываются."""
    return "u" + secrets.token_hex(3), secrets.token_hex(12)


def docker_command(login: str, password: str, port: int | None = None) -> str:
    port = port or config.PROXY_PORT
    return (
        f"docker run -d --name socks5 --restart always -p {port}:{port} "
        f"-e PROXY_USER={login} -e PROXY_PASSWORD={password} serjs/go-socks5-proxy"
    )


def new_record(owner: int, owner_name: str, host: str, login: str, password: str,
               port: int | None = None) -> dict:
    return {
        "id": secrets.token_hex(3),
        "owner": owner,
        "owner_name": owner_name,
        "host": host,
        "port": port or config.PROXY_PORT,
        "login": login,
        "password": password,
        "status": "waiting",
        "created": storage.now(),
        "last_check": "",
    }


def url(record: dict) -> str:
    return f"socks5://{record['login']}:{record['password']}@{record['host']}:{record['port']}"


async def check(proxy_url: str, timeout: int = CHECK_TIMEOUT) -> bool:
    """Любой HTTP-ответ через туннель = прокси рабочий (401/404 тоже считаются)."""
    try:
        connector = ProxyConnector.from_url(proxy_url, rdns=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(CHECK_URL, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                return response.status > 0
    except Exception as exc:
        log.debug("прокси %s не отвечает: %s", text.mask_proxy(proxy_url), exc)
        return False


async def check_direct(timeout: int = CHECK_TIMEOUT) -> bool:
    """Проверка связи без прокси — чтобы не переключаться зря."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                return response.status > 0
    except Exception:
        return False


async def check_many(urls: dict[str, str], limit: int = 5) -> dict[str, bool]:
    """Проверяем параллельно, но не больше limit одновременно.
    
    [NEW] Теперь функция сама отслеживает подряд идущие провалы по ID прокси (ключу словаря).
    Возвращает True, если прокси жив, или если он упал менее FAIL_THRESHOLD раз подряд.
    """
    semaphore = asyncio.Semaphore(limit)

    async def one(key: str, proxy_url: str):
        async with semaphore:
            is_alive = await check(proxy_url)
            
            if is_alive:
                # [NEW] Успех: сбрасываем счётчик провалов для этого ID
                _fail_counts[key] = 0
                return key, True
            else:
                # [NEW] Провал: увеличиваем счётчик
                _fail_counts[key] = _fail_counts.get(key, 0) + 1
                
                # Возвращаем False (мёртв) только если превысили порог
                is_dead = _fail_counts[key] >= FAIL_THRESHOLD
                return key, not is_dead

    results = await asyncio.gather(*(one(key, u) for key, u in urls.items()))
    return dict(results)