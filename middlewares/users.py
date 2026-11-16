"""Единственная middleware: регистрация пользователя на любой апдейт.

Важно: у Update в aiogram 3 НЕТ поля from_user.
Пользователя берём из data['event_from_user'] — его кладёт встроенная
UserContextMiddleware, которая отрабатывает раньше нашей outer-middleware.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from utils import storage

log = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not user.is_bot:
            try:
                if await storage.register_user(user.id, user.username):
                    log.info("Новый пользователь: %s (@%s)", user.id, user.username)
            except Exception:
                # запись не удалась — апдейт всё равно обрабатываем
                log.exception("Не удалось записать пользователя %s", user.id)
        return await handler(event, data)
