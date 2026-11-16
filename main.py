"""Точка входа: только запуск. Бизнес-логики здесь нет.

Порядок: логи -> данные -> Bot -> Dispatcher -> middleware -> роутеры -> фоновый тик -> polling.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from handlers import admin, history, monitor, proxy, scan, start
from middlewares.users import UserMiddleware
from utils import proxy_watch, selfcheck, storage, watcher

log = logging.getLogger(__name__)


def setup_logging() -> None:
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(config.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
        ],
    )


def build_bot() -> Bot:
    if not config.TOKEN:
        raise SystemExit("Нет TOKEN. Заполни .env (см. .env.example).")
    settings = storage.load_settings()
    proxy = settings.get("proxy") or config.PROXY_URL
    # Прокси только для соединений с Telegram. Ping идёт напрямую.
    session = AiohttpSession(proxy=proxy) if proxy else None
    return Bot(config.TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(UserMiddleware())
    for router in (start.router, scan.router, history.router, monitor.router, proxy.router, admin.router):
        dp.include_router(router)
    return dp


async def preflight(bot) -> None:
    """Проверка окружения до старта.

    ICMP критичен: без него бот будет врать «всё недоступно» и слать ложные алерты,
    поэтому падаем сразу с понятной инструкцией. Telegram — не критичен:
    polling сам повторяет попытки, просто пишем подсказку про прокси в лог.
    """
    ok, detail = await selfcheck.check_ping()
    if not ok:
        log.error("ICMP не работает:\n%s", detail)
        raise SystemExit(2)
    log.info(detail)

    ok, detail = await selfcheck.check_telegram(bot)
    if ok:
        log.info(detail)
        return
    log.error("Telegram недоступен:\n%s", detail)
    # Основной прокси может быть мёртв ещё до старта: сразу пробуем прокси участников.
    if await proxy_watch.try_recover(bot):
        log.info("Стартуем через прокси участника")


async def run_polling(dp: Dispatcher, bot: Bot) -> None:
    """Polling с восстановлением: мёртвый прокси не должен убивать бота насмерть."""
    while True:
        try:
            await dp.start_polling(bot)
            return                      # штатная остановка (SIGTERM / Ctrl+C)
        except Exception:
            log.exception("Polling оборвался, пробую восстановить связь")
            await proxy_watch.try_recover(bot)
            await asyncio.sleep(config.PROXY_CHECK_INTERVAL)


async def main() -> None:
    setup_logging()
    storage.init()
    bot = build_bot()
    dp = build_dispatcher()
    await preflight(bot)
    tasks = [
        asyncio.create_task(watcher.watch_loop(bot)),
        asyncio.create_task(proxy_watch.proxy_loop(bot)),
    ]
    log.info("Бот запущен. Мониторинг каждые %s c", config.CHECK_INTERVAL)
    try:
        await run_polling(dp, bot)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        storage.close()
        await bot.session.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
