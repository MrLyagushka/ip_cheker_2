"""/start, /help и главное inline-меню."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message

from keyboards import inline
from utils import sender

router = Router(name="start")

HELP = (
    "Что умею:\n"
    "/scan 8.8.8.8 — проверить один IP\n"
    "/scan 192.168.0.0 — проверить всю /24 (256 адресов)\n"
    "/tree — история сканов\n"
    "/watch 8.8.8.8 — добавить IP в мониторинг\n"
    "/unwatch — убрать IP из мониторинга\n"
    "/myips — мои IP и их статус\n"
    "/help — эта справка\n"
    "/id — показать chat_id и id темы (нужно для настройки алертов)\n\n"
    "Мониторинг проверяет адреса раз в час и сообщает в общий чат "
    "только когда статус изменился."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await sender.safe_send(
        message.bot, message.chat.id, f"Привет! Я проверяю доступность IP.\n\n{HELP}",
        reply_markup=inline.main_menu(), **sender.thread_kwargs(message),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await sender.safe_send(
        message.bot, message.chat.id, HELP, reply_markup=inline.main_menu(),
        **sender.thread_kwargs(message),
    )


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    """Служебная команда: чем заполнить ALERT_CHAT_ID и ALERT_THREAD_ID."""
    thread_id = message.message_thread_id
    body = (
        f"chat_id: {message.chat.id}\n"
        f"твой user_id: {message.from_user.id}\n"
        f"id темы: {thread_id if thread_id else 'нет (General или личный чат)'}\n\n"
        "Чтобы алерты шли в эту тему, напиши команду /id прямо в ней и заполни .env:\n"
        "ALERT_CHAT_ID = chat_id, ALERT_THREAD_ID = id темы."
    )
    await sender.safe_send(message.bot, message.chat.id, body, **sender.thread_kwargs(message))


@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery) -> None:
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            HELP, reply_markup=inline.back(),
        )
    await callback.answer()


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery) -> None:
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Главное меню", reply_markup=inline.main_menu(),
        )
    await callback.answer()
