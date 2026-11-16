"""Фоновый мониторинг: один цикл, один тик, алерты ТОЛЬКО при смене статуса.

Алерты уходят в нужную тему супергруппы: ALERT_CHAT_ID + ALERT_THREAD_ID.
Личных рассылок нет.
Статусы в tracked.json меняет только этот тик — ручная проверка их не трогает,
чтобы не «съесть» будущее изменение.
"""
from __future__ import annotations

import asyncio
import logging

import config
from utils import ping, sender, storage, text

log = logging.getLogger(__name__)


async def send_alert(bot, body: str) -> bool:
    """Алерт в нужную тему супергруппы.

    Если тема закрыта/удалена или id неверный — Telegram вернёт ошибку,
    и мы один раз отправляем в General, чтобы алерт не потерялся молча.
    """
    thread_id = config.ALERT_THREAD_ID
    if thread_id:
        if await sender.safe_send(bot, config.ALERT_CHAT_ID, body, message_thread_id=thread_id):
            return True
        log.warning("Тема %s недоступна, отправляю в General", thread_id)
    return await sender.safe_send(bot, config.ALERT_CHAT_ID, body)


async def tick(bot) -> dict[str, tuple[str, str]]:
    """Один проход. Возвращает найденные изменения {ip: (old, new)}."""
    tracked = storage.all_tracked()
    ips = sorted({item["ip"] for items in tracked.values() for item in items if item.get("ip")})
    if not ips:
        return {}

    results = await ping.ping_many(ips, limit=config.load_settings()["ping_limit"])

    changes: dict[str, tuple[str, str]] = {}
    for uid, items in tracked.items():
        try:  # один проблемный пользователь не мешает остальным
            for item in items:
                ip = item["ip"]
                new = "up" if results.get(ip) else "down"
                old = item.get("status", "unknown")
                # первое наблюдение (unknown) — не алертим, иначе спам при /watch
                if old in ("up", "down") and old != new and ip not in changes:
                    changes[ip] = (old, new)
                item["status"] = new
        except Exception:
            log.exception("Ошибка обработки пользователя %s", uid)

    await storage.save_tracked(tracked)

    if changes:
        if config.ALERT_CHAT_ID:
            await send_alert(bot, text.changes_text(changes))
        else:
            log.warning("ALERT_CHAT_ID не задан, алерт не отправлен: %s", changes)
    return changes


async def watch_loop(bot) -> None:
    """Цикл и «supervisor» в одном месте: упавший тик не убивает цикл."""
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("Тик мониторинга упал, продолжаем работать")
        await asyncio.sleep(config.CHECK_INTERVAL)
