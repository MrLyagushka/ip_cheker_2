"""Админ-панель: лимит пингов, прокси, статистика, чистка истории, рассылка.

Доступ — один фильтр на роутер: message/callback от ADMIN_ID.
Если ADMIN_ID не задан (0), панель недоступна никому.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
from handlers import scan as scan_handler
from keyboards import inline
from utils import text
from utils import sender
from utils import storage

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(F.from_user.id == config.ADMIN_ID)
router.callback_query.filter(F.from_user.id == config.ADMIN_ID)

BC_CANCEL = asyncio.Event()  # флаг отмены рассылки


class AdminSG(StatesGroup):
    wait_limit = State()
    wait_proxy = State()
    wait_broadcast = State()


def panel_text() -> str:
    settings = config.load_settings()
    return (
        "🛠 Админ-панель\n"
        f"Лимит одновременных пингов: {settings['ping_limit']}\n"
        f"Прокси: {text.esc(settings.get('proxy') or 'нет')}\n\n"
        "Лимит применяется со следующего скана.\n"
        "Прокси — после перезапуска бота."
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await sender.safe_send(
        message.bot, message.chat.id, panel_text(),
        reply_markup=inline.admin_menu(config.load_settings()),
    )


@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery) -> None:
    body = text.stats_text(
        storage.all_users(),
        storage.read_json(config.HISTORY_FILE, {}),
        storage.all_tracked(),
        len(scan_handler.BUSY),
    )
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            body, reply_markup=inline.admin_menu(config.load_settings()),
        )
    await callback.answer()


@router.callback_query(F.data == "adm:limit")
async def cb_limit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSG.wait_limit)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            f"Пришли число от 1 до {config.PING_LIMIT_MAX}", reply_markup=inline.back(),
        )
    await callback.answer()


@router.message(AdminSG.wait_limit)
async def got_limit(message: Message, state: FSMContext) -> None:
    await state.clear()
    value = config.to_int(message.text, 0)
    if not 1 <= value <= config.PING_LIMIT_MAX:
        await sender.safe_send(
            message.bot, message.chat.id, f"⚠️ Нужно число 1…{config.PING_LIMIT_MAX}"
        )
        return
    await storage.save_settings({"ping_limit": value})
    await sender.safe_send(
        message.bot, message.chat.id,
        f"✅ Лимит пингов: {value}. Применится со следующего скана.",
        reply_markup=inline.back(),
    )


@router.callback_query(F.data == "adm:proxy")
async def cb_proxy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSG.wait_proxy)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Пришли socks5://user:pass@host:port или off", reply_markup=inline.back(),
        )
    await callback.answer()


@router.message(AdminSG.wait_proxy)
async def got_proxy(message: Message, state: FSMContext) -> None:
    await state.clear()
    raw = (message.text or "").strip()
    value = "" if raw.lower() in ("off", "нет", "-") else raw
    if value and "://" not in value:
        await sender.safe_send(message.bot, message.chat.id, "⚠️ Формат: socks5://host:port или off")
        return
    await storage.save_settings({"proxy": value})
    await sender.safe_send(
        message.bot, message.chat.id,
        "✅ Записал. Прокси применится после перезапуска бота.", reply_markup=inline.back(),
    )


@router.callback_query(F.data == "adm:clear")
async def cb_clear(callback: CallbackQuery) -> None:
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Удалить историю сканов ВСЕХ пользователей?",
            reply_markup=inline.confirm("adm:clear:yes", "menu"),
        )
    await callback.answer()


@router.callback_query(F.data == "adm:clear:yes")
async def cb_clear_yes(callback: CallbackQuery) -> None:
    removed = await storage.clear_history()
    log.info("Админ %s очистил историю (%s записей)", callback.from_user.id, removed)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            f"🗑 Удалено записей: {removed}", reply_markup=inline.back(),
        )
    await callback.answer("Готово")


@router.callback_query(F.data == "adm:bc")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminSG.wait_broadcast)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Пришли текст рассылки (уйдёт всем пользователям)", reply_markup=inline.back(),
        )
    await callback.answer()


@router.message(AdminSG.wait_broadcast)
async def got_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    BC_CANCEL.clear()
    chat_ids = [config.to_int(uid, 0) for uid in storage.all_users()]
    head = await sender.send(
        message.bot, message.chat.id, f"📣 Рассылаю {len(chat_ids)} пользователям…",
        reply_markup=inline.broadcast_cancel(),
    )
    # parse_mode=None: текст админа отправляем как есть, без риска HTML-ошибок
    sent, failed = await sender.broadcast(
        message.bot, chat_ids, message.text or "", cancel=BC_CANCEL, parse_mode=None
    )
    report = f"📣 Отправлено: {sent}, ошибок: {failed}"
    if BC_CANCEL.is_set():
        report += " (отменено)"
    if isinstance(head, Message):
        await sender.safe_edit(message.bot, message.chat.id, head.message_id, report, reply_markup=inline.back())
    else:
        await sender.safe_send(message.bot, message.chat.id, report, reply_markup=inline.back())


@router.callback_query(F.data == "adm:bc:cancel")
async def cb_broadcast_cancel(callback: CallbackQuery) -> None:
    BC_CANCEL.set()
    await callback.answer("Останавливаю рассылку…")
