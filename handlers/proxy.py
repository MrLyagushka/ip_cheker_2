"""/get_proxy — участник поднимает свой SOCKS5 и поддерживает бота.

Порядок: бот выдаёт команду с логином/паролем → участник присылает IP сервера →
бот ждёт запуска, проверяет туннель и сообщает в чат уведомлений.
Дальше за прокси следит utils/proxy_watch.py (падение → тэг владельца).
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from keyboards import inline
from utils import ips as ips_tools
from utils import proxies, proxy_watch, sender, storage, text

log = logging.getLogger(__name__)
router = Router(name="proxy")


class ProxySG(StatesGroup):
    wait_host = State()


async def ask_host(bot, chat_id: int, state: FSMContext, thread: dict) -> None:
    login, password = proxies.new_credentials()
    await state.set_state(ProxySG.wait_host)
    await state.update_data(login=login, password=password)
    body = text.proxy_invite(proxies.docker_command(login, password))
    await sender.safe_send(
        bot, chat_id, body + "\n\nПришли IP сервера, где запустишь контейнер.",
        reply_markup=inline.back(), **thread,
    )


async def register(message: Message, host_raw: str, login: str | None, password: str | None) -> None:
    thread = sender.thread_kwargs(message)
    if not login or not password:
        await sender.safe_send(message.bot, message.chat.id, "Начни заново: /get_proxy", **thread)
        return
    try:
        host = ips_tools.parse_single(host_raw)
    except ValueError as exc:
        await sender.safe_send(message.bot, message.chat.id, f"⚠️ {exc}", **thread)
        return
    mine = [item for item in storage.all_proxies() if item["owner"] == message.from_user.id]
    if len(mine) >= config.PROXY_MAX_PER_USER:
        await sender.safe_send(
            message.bot, message.chat.id,
            f"⚠️ У тебя уже {len(mine)} прокси (лимит {config.PROXY_MAX_PER_USER}). "
            "Убери лишний: /proxies", **thread,
        )
        return
    record = proxies.new_record(
        message.from_user.id, message.from_user.first_name, host, login, password,
    )
    storage.add_proxy(record)
    log.info("Новый прокси %s:%s от %s", host, record["port"], message.from_user.id)
    await sender.safe_send(
        message.bot, message.chat.id,
        f"⏳ Жду запуска прокси {host}:{record['port']}.\n"
        f"Проверяю каждые {config.PROXY_CHECK_INTERVAL} секунд и напишу в чат уведомлений, "
        "как только он заработает.",
        reply_markup=inline.back(), **thread,
    )


@router.message(Command("get_proxy"))
async def cmd_get_proxy(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        login, password = proxies.new_credentials()
        await state.clear()
        await sender.safe_send(
            message.bot, message.chat.id,
            text.proxy_invite(proxies.docker_command(login, password)),
            **sender.thread_kwargs(message),
        )
        await register(message, command.args, login, password)
        return
    await ask_host(message.bot, message.chat.id, state, sender.thread_kwargs(message))


@router.callback_query(F.data == "px:new")
async def cb_new(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message:
        await ask_host(callback.bot, callback.message.chat.id, state,
                       sender.thread_kwargs(callback.message))
    await callback.answer()


@router.message(ProxySG.wait_host)
async def got_host(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    await register(message, message.text or "", data.get("login"), data.get("password"))


async def show_proxies(bot, chat_id: int, uid: int, message_id: int | None = None,
                       thread_id: int | None = None) -> None:
    is_admin = uid == config.ADMIN_ID
    records = storage.all_proxies()
    if not is_admin:
        records = [record for record in records if record["owner"] == uid]
    body = text.proxies_text(records, is_admin)
    markup = inline.proxies_list(records, is_admin)
    if message_id is None:
        thread = {"message_thread_id": thread_id} if thread_id else {}
        await sender.safe_send(bot, chat_id, body, reply_markup=markup, **thread)
    else:
        await sender.safe_edit(bot, chat_id, message_id, body, reply_markup=markup)


@router.message(Command("proxies"))
async def cmd_proxies(message: Message) -> None:
    await show_proxies(message.bot, message.chat.id, message.from_user.id,
                       thread_id=message.message_thread_id)


@router.callback_query(F.data == "px:list")
async def cb_list(callback: CallbackQuery) -> None:
    if callback.message:
        await show_proxies(callback.bot, callback.message.chat.id, callback.from_user.id,
                           callback.message.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("px:rm:"))
async def cb_remove(callback: CallbackQuery) -> None:
    record = storage.get_proxy(callback.data.split(":")[-1])
    uid = callback.from_user.id
    if record is None:
        await callback.answer("Уже удалён")
        return
    if record["owner"] != uid and uid != config.ADMIN_ID:
        await callback.answer("Это чужой прокси", show_alert=True)
        return
    storage.remove_proxy(record["id"])
    if callback.message:
        await show_proxies(callback.bot, callback.message.chat.id, uid, callback.message.message_id)
    await callback.answer("Убрал прокси")


@router.callback_query(F.data.startswith("px:use:"))
async def cb_use(callback: CallbackQuery) -> None:
    """Ручное подключение живого прокси — только админ."""
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Только админ", show_alert=True)
        return
    record = storage.get_proxy(callback.data.split(":")[-1])
    if record is None:
        await callback.answer("Прокси не найден")
        return
    await proxy_watch.switch(callback.bot, proxies.url(record))
    await callback.answer("Подключил")
    if callback.message:
        await show_proxies(callback.bot, callback.message.chat.id, callback.from_user.id,
                           callback.message.message_id)
