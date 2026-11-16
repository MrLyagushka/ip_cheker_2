"""Сеть прокси участников: ждём запуска, тэгаем владельца при падении, переключаемся.

Статусы: waiting (ждём запуска) -> up -> down -> up ... , либо waiting -> expired.
Все сообщения уходят туда же, куда алерты мониторинга: ALERT_CHAT_ID + тема.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram.client.session.aiohttp import AiohttpSession

import config
from utils import proxies, selfcheck, storage, text, watcher

log = logging.getLogger(__name__)


def hours_since(moment: str) -> float:
    try:
        return (datetime.now() - datetime.strptime(moment, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
    except (TypeError, ValueError):
        return 0.0


def next_status(old: str, alive: bool, created: str) -> str:
    if alive:
        return "up"
    if old == "waiting":
        return "expired" if hours_since(created) >= config.PROXY_WAIT_HOURS else "waiting"
    if old == "expired":
        return "expired"
    return "down"


async def notify(bot, record: dict, old: str, new: str) -> None:
    who = text.mention(record["owner"], record["owner_name"])
    where = f"{record['host']}:{record['port']}"
    if new == "up" and old == "waiting":
        body = f"✅ {who}, прокси {where} запущен и работает. Спасибо за поддержку бота!"
    elif new == "up" and old == "down":
        body = f"✅ {who}, прокси {where} снова в строю."
    elif new == "up" and old == "expired":
        body = f"✅ {who}, прокси {where} ожил — заявка снова активна."
    elif new == "down":
        body = (f"⚠️ {who}, твой прокси {where} перестал отвечать.\n"
                "Проверь на сервере: docker ps -a | grep socks5 и docker logs socks5")
    elif new == "expired":
        body = (f"⌛ {who}, прокси {where} так и не появился за {config.PROXY_WAIT_HOURS} ч. "
                "Заявка снята, команду можно взять снова: /get_proxy")
    else:
        return
    await watcher.send_alert(bot, body)


async def switch(bot, new_url: str) -> None:
    """Меняем прокси на ходу: новая сессия вместо старой, настройку запоминаем в БД."""
    old_session = bot.session
    bot.session = AiohttpSession(proxy=new_url) if new_url else AiohttpSession()
    try:
        await old_session.close()
    except Exception:
        log.debug("старая сессия уже закрыта")
    await storage.save_settings({"proxy": new_url})
    log.info("Прокси переключён на %s", text.mask_proxy(new_url))


async def failover(bot, records: list[dict], alive: dict[str, bool]) -> str | None:
    """Авто-переключение. Возвращает 'main', id прокси или None (для логов и тестов)."""
    active = storage.load_settings().get("proxy") or ""
    main_url = config.PROXY_URL or ""

    # 1. Основной прокси из .env ожил — возвращаемся на него.
    if main_url and active != main_url and await proxies.check(main_url):
        await switch(bot, main_url)
        await watcher.send_alert(bot, "🔁 Основной прокси снова работает — вернулся на него.")
        return "main"

    # 2. Текущий путь жив — ничего не трогаем.
    known = {proxies.url(record): alive.get(record["id"], False) for record in records}
    if active:
        if known.get(active, await proxies.check(active)):
            return None
    elif await proxies.check_direct():
        return None

    # 3. Текущий путь мёртв — берём первый живой прокси участника.
    for record in records:
        if not alive.get(record["id"]):
            continue
        candidate = proxies.url(record)
        if candidate == active:
            continue
        await switch(bot, candidate)
        await watcher.send_alert(
            bot,
            "🔁 Основной прокси недоступен — работаю через прокси "
            f"{text.mention(record['owner'], record['owner_name'])} ({record['host']}:{record['port']}).",
        )
        return record["id"]

    log.warning("Живых прокси нет, остаюсь на текущем пути")
    return None


async def try_recover(bot) -> bool:
    """Пробуем вернуть связь: проверяем прокси участников и переключаемся на живой."""
    records = storage.all_proxies()
    alive = await proxies.check_many({r["id"]: proxies.url(r) for r in records}) if records else {}
    await failover(bot, records, alive)
    ok, detail = await selfcheck.check_telegram(bot)
    if ok:
        log.info("Связь восстановлена: %s", detail)
    return ok


async def tick(bot) -> dict:
    """Один проход по всем прокси. Возвращает случившиеся переходы статусов."""
    records = storage.all_proxies()
    if not records:
        return {}          # сети участников нет — переключаться не на что
    alive = await proxies.check_many({r["id"]: proxies.url(r) for r in records})
    changes: dict[str, tuple[str, str]] = {}
    for record in records:
        old = record["status"]
        new = next_status(old, alive.get(record["id"], False), record["created"])
        storage.set_proxy_status(record["id"], new)
        if new != old:
            changes[record["id"]] = (old, new)
            try:
                await notify(bot, record, old, new)
            except Exception:
                log.exception("Не удалось уведомить о прокси %s", record["id"])
    try:
        await failover(bot, records, alive)
    except Exception:
        log.exception("Переключение прокси не удалось")
    return changes


async def proxy_loop(bot) -> None:
    """Тот же принцип, что и у мониторинга: один цикл, ошибка не убивает цикл."""
    while True:
        try:
            await tick(bot)
        except Exception:
            log.exception("Проверка прокси упала, продолжаем")
        await asyncio.sleep(config.PROXY_CHECK_INTERVAL)
