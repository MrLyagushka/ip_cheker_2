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
from handlers import start
from handlers import admin
from handlers import history
from handlers import monitor
from handlers import scan
from middlewares.users import UserMiddleware
from utils import watcher
from utils import storage

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
    settings = config.load_settings()
    proxy = settings.get("proxy") or config.PROXY_URL
    # Прокси только для соединений с Telegram. Ping идёт напрямую.
    session = AiohttpSession(proxy=proxy) if proxy else None
    return Bot(config.TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(UserMiddleware())
    for router in (start.router, scan.router, history.router, monitor.router, admin.router):
        dp.include_router(router)
    return dp


async def main() -> None:
    setup_logging()
    storage.init()
    bot = build_bot()
    dp = build_dispatcher()
    task = asyncio.create_task(watcher.watch_loop(bot))
    log.info("Бот запущен. Мониторинг каждые %s c", config.CHECK_INTERVAL)
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await bot.session.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
