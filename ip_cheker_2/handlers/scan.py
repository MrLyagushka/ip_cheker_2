"""Интерактивное сканирование: /scan, ввод адреса, прогресс, отмена.

Здесь же живёт блокировка «один скан на пользователя»:
BUSY + try/finally. Никакого TTL не нужно — finally снимает флаг всегда.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from keyboards import inline
from utils import ips as ips_tools
from utils import ping, sender, storage, text

log = logging.getLogger(__name__)
router = Router(name="scan")

BUSY: set[int] = set()
CANCELS: dict[int, asyncio.Event] = {}


class ScanSG(StatesGroup):
    wait_target = State()


@router.message(Command("scan"))
async def cmd_scan(message: Message, command: CommandObject, state: FSMContext) -> None:
    if command.args:
        await state.clear()
        await run_scan(
            message.bot, message.chat.id, message.from_user.id, command.args,
            thread_id=message.message_thread_id,
        )
        return
    await state.set_state(ScanSG.wait_target)
    await sender.safe_send(
        message.bot, message.chat.id,
        "Пришли IPv4 (8.8.8.8) или сеть (192.168.0.0)", reply_markup=inline.back(),
        **sender.thread_kwargs(message),
    )


@router.callback_query(F.data == "scan:start")
async def cb_scan_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ScanSG.wait_target)
    if callback.message:
        await sender.safe_edit(
            callback.bot, callback.message.chat.id, callback.message.message_id,
            "Пришли IPv4 (8.8.8.8) или сеть (192.168.0.0)", reply_markup=inline.back(),
        )
    await callback.answer()


@router.message(ScanSG.wait_target)
async def got_target(message: Message, state: FSMContext) -> None:
    await state.clear()
    await run_scan(
        message.bot, message.chat.id, message.from_user.id, message.text or "",
        thread_id=message.message_thread_id,
    )


@router.callback_query(F.data == "scan:cancel")
async def cb_scan_cancel(callback: CallbackQuery) -> None:
    event = CANCELS.get(callback.from_user.id)
    if event is None:
        await callback.answer("Активного скана нет")
        return
    event.set()
    await callback.answer("Отменяю…")


async def run_scan(bot, chat_id: int, uid: int, raw: str, thread_id: int | None = None) -> None:
    """Вся последовательность скана. Вызывается и из команды, и из FSM-ввода.

    thread_id — тема супергруппы, если команду написали в теме (в личке None).
    """
    thread = {"message_thread_id": thread_id} if thread_id else {}
    try:
        targets, kind = ips_tools.parse_target(raw)
    except ValueError as exc:
        await sender.safe_send(bot, chat_id, f"⚠️ {exc}", **thread)
        return

    if uid in BUSY:
        await sender.safe_send(
            bot, chat_id, "⏳ У тебя уже идёт сканирование. Дождись конца или нажми «Отмена».",
            **thread,
        )
        return

    label = targets[0] if kind == "host" else ips_tools.subnet_label(targets[0])
    BUSY.add(uid)
    cancel = asyncio.Event()
    CANCELS[uid] = cancel
    try:
        head = await sender.send(
            bot, chat_id, f"🔍 Проверяю {len(targets)} адрес(ов)…",
            reply_markup=inline.cancel_scan() if kind == "subnet" else None, **thread,
        )
        head_id = head.message_id if isinstance(head, Message) else None

        async def progress(done: int, total: int) -> None:
            if head_id is not None:
                await sender.safe_edit(
                    bot, chat_id, head_id, f"🔍 Проверено {done}/{total}…",
                    reply_markup=inline.cancel_scan(),
                )

        results = await ping.ping_many(
            targets,
            limit=storage.load_settings()["ping_limit"],
            progress=progress if kind == "subnet" else None,
            cancel=cancel,
        )
    finally:
        BUSY.discard(uid)
        CANCELS.pop(uid, None)

    summary = text.scan_summary(label, kind, results, cancelled=cancel.is_set())
    await storage.add_history(uid, {
        "ts": storage.now(),
        "type": kind,
        "target": label,
        "up": sum(1 for ok in results.values() if ok),
        "total": len(results),
    })

    if kind == "subnet":
        path = storage.save_result(uid, text.result_file(label, results))
        await sender.safe_document(bot, chat_id, FSInputFile(path), caption=summary, **thread)

    if head_id is not None:
        await sender.safe_edit(bot, chat_id, head_id, summary, reply_markup=inline.back())
    else:
        await sender.safe_send(bot, chat_id, summary, reply_markup=inline.back(), **thread)
