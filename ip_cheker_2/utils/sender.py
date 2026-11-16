"""Отправка сообщений с повторами по flood-control.

Одна функция _call с логикой повторов + три тонкие обёртки.
Ни одна функция наружу не бросает исключение: сбой доставки не должен
ронять ни хендлер, ни часовой тик.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

log = logging.getLogger(__name__)

ATTEMPTS = 3
PACE = 0.1  # пауза между сообщениями массовой рассылки


def thread_kwargs(message) -> dict:
    """Отвечать в ту же тему супергруппы, откуда пришла команда.

    В личке и в General темы нет -> пустой словарь, ничего не передаём.
    Нужен только для отправки: edit_message_text адресует сообщение по message_id.
    """
    thread_id = getattr(message, "message_thread_id", None)
    return {"message_thread_id": thread_id} if thread_id else {}


async def _call(method, *args, **kwargs):
    """Возвращает результат метода, True для «message is not modified», None при провале."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return await method(*args, **kwargs)
        except TelegramRetryAfter as exc:
            log.warning("flood-control, ждём %s c", exc.retry_after)
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError:
            log.info("чат недоступен (бот заблокирован?)")
            return None  # повторять бессмысленно
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return True
            log.warning("bad request: %s", exc)
            return None  # повтор не поможет
        except Exception:
            log.warning("сбой отправки, попытка %s/%s", attempt, ATTEMPTS, exc_info=True)
            if attempt < ATTEMPTS:
                await asyncio.sleep(1)
    return None


async def send(bot, chat_id: int, text: str, **kwargs):
    """Отправить и вернуть Message (нужно, когда потом редактируем прогресс)."""
    return await _call(bot.send_message, chat_id, text, **kwargs)


async def safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    return bool(await send(bot, chat_id, text, **kwargs))


async def safe_edit(bot, chat_id: int, message_id: int, text: str, **kwargs) -> bool:
    return bool(
        await _call(
            bot.edit_message_text, chat_id=chat_id, message_id=message_id, text=text, **kwargs
        )
    )


async def safe_document(bot, chat_id: int, document, caption: str | None = None, **kwargs) -> bool:
    return bool(
        await _call(bot.send_document, chat_id=chat_id, document=document, caption=caption, **kwargs)
    )


async def broadcast(
    bot, chat_ids, text: str, cancel: asyncio.Event | None = None, **kwargs
) -> tuple[int, int]:
    """Рассылка по очереди с паузой. Возвращает (отправлено, ошибок)."""
    sent = failed = 0
    for chat_id in chat_ids:
        if cancel is not None and cancel.is_set():
            break
        if await safe_send(bot, chat_id, text, **kwargs):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(PACE)
    return sent, failed
