"""/tree — история сканов пользователя."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from keyboards import inline
from utils import sender, storage, text

router = Router(name="history")


async def show_history(
    bot, chat_id: int, uid: int, message_id: int | None = None, thread_id: int | None = None
) -> None:
    body = text.history_text(storage.get_history(uid))
    markup = inline.history_actions()
    if message_id is None:
        thread = {"message_thread_id": thread_id} if thread_id else {}
        await sender.safe_send(bot, chat_id, body, reply_markup=markup, **thread)
    else:
        await sender.safe_edit(bot, chat_id, message_id, body, reply_markup=markup)


@router.message(Command("tree"))
async def cmd_tree(message: Message) -> None:
    await show_history(
        message.bot, message.chat.id, message.from_user.id, thread_id=message.message_thread_id
    )


@router.callback_query(F.data == "hist:show")
async def cb_show(callback: CallbackQuery) -> None:
    if callback.message:
        await show_history(
            callback.bot, callback.message.chat.id, callback.from_user.id,
            callback.message.message_id, callback.message.message_thread_id,
        )
    await callback.answer()


@router.callback_query(F.data == "hist:clear")
async def cb_clear(callback: CallbackQuery) -> None:
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Удалить всю твою историю сканов?",
            reply_markup=inline.confirm("hist:clear:yes", "hist:show"),
        )
    await callback.answer()


@router.callback_query(F.data == "hist:clear:yes")
async def cb_clear_yes(callback: CallbackQuery) -> None:
    removed = await storage.clear_history(callback.from_user.id)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            f"🗑 Удалено записей: {removed}", reply_markup=inline.back(),
        )
    await callback.answer("История очищена")
