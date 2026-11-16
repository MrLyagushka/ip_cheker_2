"""Личный список мониторинга: /watch, /unwatch, /myips и inline-кнопки.

Алерты по этим адресам уходят в общий чат (utils/watcher.py),
здесь только управление своим списком и ручная проверка.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from keyboards import inline
from utils import ips as ips_tools
from utils import ping, sender, storage, text

router = Router(name="monitor")


class MonSG(StatesGroup):
    wait_ip = State()


async def show_list(
    bot, chat_id: int, uid: int, message_id: int | None = None, thread_id: int | None = None
) -> None:
    items = storage.get_tracked(uid)
    body = text.myips_text(items)
    markup = inline.myips(items)
    if message_id is None:
        thread = {"message_thread_id": thread_id} if thread_id else {}
        await sender.safe_send(bot, chat_id, body, reply_markup=markup, **thread)
    else:
        await sender.safe_edit(bot, chat_id, message_id, body, reply_markup=markup)


async def add_ip(bot, chat_id: int, uid: int, raw: str, thread_id: int | None = None) -> None:
    thread = {"message_thread_id": thread_id} if thread_id else {}
    try:
        ip = ips_tools.parse_single(raw)
    except ValueError as exc:
        await sender.safe_send(bot, chat_id, f"⚠️ {exc}", **thread)
        return
    status = await storage.add_tracked(uid, ip)
    if status == "ok":
        body = f"✅ {ip} добавлен. Проверяю раз в час, об изменениях скажу в общий чат."
    elif status == "dup":
        body = f"ℹ️ {ip} уже в списке."
    else:
        body = f"⚠️ Лимит {config.MAX_WATCH} адресов. Убери лишний через /unwatch."
    await sender.safe_send(bot, chat_id, body, reply_markup=inline.back(), **thread)


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        await state.clear()
        await add_ip(
            message.bot, message.chat.id, message.from_user.id, command.args,
            thread_id=message.message_thread_id,
        )
        return
    await state.set_state(MonSG.wait_ip)
    await sender.safe_send(
        message.bot, message.chat.id, "Пришли одиночный IPv4 для мониторинга",
        reply_markup=inline.back(), **sender.thread_kwargs(message),
    )


@router.message(MonSG.wait_ip)
async def got_ip(message: Message, state: FSMContext) -> None:
    await state.clear()
    await add_ip(
        message.bot, message.chat.id, message.from_user.id, message.text or "",
        thread_id=message.message_thread_id,
    )


@router.message(Command("myips", "unwatch"))
async def cmd_list(message: Message) -> None:
    await show_list(
        message.bot, message.chat.id, message.from_user.id, thread_id=message.message_thread_id
    )


@router.callback_query(F.data == "mon:list")
async def cb_list(callback: CallbackQuery) -> None:
    if callback.message:
        await show_list(
            callback.bot, callback.message.chat.id, callback.from_user.id,
            callback.message.message_id, callback.message.message_thread_id,
        )
    await callback.answer()


@router.callback_query(F.data == "mon:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MonSG.wait_ip)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Пришли одиночный IPv4 для мониторинга", reply_markup=inline.back(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("mon:rm:"))
async def cb_remove(callback: CallbackQuery) -> None:
    # Индекс в списке НАЖАВШЕГО: чужой список тронуть невозможно.
    index = config.to_int(callback.data.split(":")[-1], -1)
    ip = await storage.remove_tracked(callback.from_user.id, index)
    if callback.message:
        await show_list(
            callback.bot, callback.message.chat.id, callback.from_user.id,
            callback.message.message_id, callback.message.message_thread_id,
        )
    await callback.answer(f"Убрал {ip}" if ip else "Уже удалён")


@router.callback_query(F.data == "mon:check")
async def cb_check(callback: CallbackQuery) -> None:
    """Ручная проверка своих адресов. Статусы в файл НЕ пишем — это делает только тик."""
    items = storage.get_tracked(callback.from_user.id)
    ips = [item["ip"] for item in items if item.get("ip")]
    if not ips:
        await callback.answer("Список пуст", show_alert=True)
        return
    await callback.answer("Проверяю…")
    results = await ping.ping_many(ips, limit=storage.load_settings()["ping_limit"])
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            text.check_text(results), reply_markup=inline.myips(items),
        )
