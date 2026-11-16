"""ICMP через локальный subprocess. Прокси здесь НЕ участвует вообще.

Результат определяется кодом возврата, а не текстом вывода ping
(исключение — Windows, там нужен признак ttl=).
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform.startswith("win")
TIMEOUT = 2.0          # секунд на один адрес
PROGRESS_EVERY = 2.0   # не чаще, чем раз в 2 секунды (иначе flood-control)


def build_cmd(ip: str) -> list[str]:
    if IS_WINDOWS:
        return ["ping", "-n", "1", "-w", "1000", ip]
    return ["ping", "-c", "1", "-W", "1", ip]


async def ping_one(ip: str) -> tuple[str, bool]:
    """Никогда не бросает исключение: любая ошибка = адрес недоступен."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *build_cmd(ip),
            stdout=asyncio.subprocess.PIPE if IS_WINDOWS else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        if proc.returncode != 0:
            # 1 = адрес не ответил; 2+ = ошибка самого ping (права/аргументы).
            # В Docker это главный признак «ICMP запрещён», а не «хост лежит».
            if not IS_WINDOWS and proc.returncode >= 2:
                log.warning(
                    "ping %s: код %s — адрес не пингуется (например, адрес сети x.x.0). "
                    "Если так со ВСЕМИ адресами — проверь окружение: python -m utils.selfcheck",
                    ip, proc.returncode,
                )
            return ip, False
        if IS_WINDOWS:
            # Windows умеет вернуть 0 при "Destination host unreachable".
            return ip, b"ttl=" in (out or b"").lower()
        return ip, True
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            except Exception:  # процесс уже умер — это не ошибка
                log.debug("kill failed for %s", ip)
        return ip, False
    except Exception:
        log.warning("ping %s упал", ip, exc_info=True)
        return ip, False


async def ping_many(
    ips: list[str],
    limit: int = 32,
    progress=None,
    cancel: asyncio.Event | None = None,
) -> dict[str, bool]:
    """Пингует список с ограничением одновременных запросов.

    limit    — размер семафора, создаётся ЗАНОВО на каждый вызов,
               поэтому новый лимит админа применяется со следующего скана.
    progress — async-функция progress(done, total).
    cancel   — Event: если установлен, оставшиеся адреса пропускаются.
    Возвращает {ip: bool} только по реально проверенным адресам.
    """
    semaphore = asyncio.Semaphore(max(1, int(limit)))
    results: dict[str, bool] = {}
    total = len(ips)
    done = 0
    last_report = time.monotonic()  # отсчёт от старта скана, а не от нуля

    async def one(ip: str) -> None:
        nonlocal done, last_report
        if cancel is not None and cancel.is_set():
            return
        async with semaphore:
            if cancel is not None and cancel.is_set():
                return
            checked_ip, alive = await ping_one(ip)
        results[checked_ip] = alive
        done += 1
        if progress is not None and (done == total or time.monotonic() - last_report >= PROGRESS_EVERY):
            last_report = time.monotonic()
            await progress(done, total)

    await asyncio.gather(*(one(ip) for ip in ips))
    return results
