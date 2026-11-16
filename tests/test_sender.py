import asyncio

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import EditMessageText, SendMessage

from utils import sender


def method():
    return SendMessage(chat_id=1, text="x")


def test_safe_send_ok(bot):
    assert asyncio.run(sender.safe_send(bot, 1, "привет")) is True
    assert bot.texts() == ["привет"]


def test_retry_after_is_honoured(make_bot, sleeps):
    bot = make_bot({"SendMessage": [
        TelegramRetryAfter(method=method(), message="Too Many Requests", retry_after=2),
        None,
    ]})
    assert asyncio.run(sender.safe_send(bot, 1, "x")) is True
    assert len(bot.sent) == 2
    assert sleeps == [3]  # retry_after + 1


def test_forbidden_is_not_retried(make_bot, sleeps):
    bot = make_bot({"SendMessage": [
        TelegramForbiddenError(method=method(), message="Forbidden: bot was blocked by the user"),
    ]})
    assert asyncio.run(sender.safe_send(bot, 1, "x")) is False
    assert len(bot.sent) == 1
    assert sleeps == []


def test_message_not_modified_is_success(make_bot):
    bot = make_bot({"EditMessageText": [
        TelegramBadRequest(method=EditMessageText(chat_id=1, message_id=1, text="x"),
                           message="Bad Request: message is not modified"),
    ]})
    assert asyncio.run(sender.safe_edit(bot, 1, 1, "x")) is True
    assert len(bot.edits) == 1


def test_other_bad_request_is_not_retried(make_bot, sleeps):
    bot = make_bot({"SendMessage": [
        TelegramBadRequest(method=method(), message="Bad Request: chat not found"),
    ]})
    assert asyncio.run(sender.safe_send(bot, 1, "x")) is False
    assert len(bot.sent) == 1


def test_unknown_error_retries_three_times(make_bot, sleeps):
    bot = make_bot({"SendMessage": [RuntimeError("сеть"), RuntimeError("сеть"), RuntimeError("сеть")]})
    assert asyncio.run(sender.safe_send(bot, 1, "x")) is False
    assert len(bot.sent) == sender.ATTEMPTS
    assert len(sleeps) == sender.ATTEMPTS - 1


def test_document_send(bot):
    assert asyncio.run(sender.safe_document(bot, 1, "file", caption="итог")) is True
    assert bot.documents[0].caption == "итог"


def test_broadcast_paces_and_counts(make_bot, sleeps):
    bot = make_bot({"SendMessage": [None, TelegramForbiddenError(method=method(), message="Forbidden"), None]})
    sent, failed = asyncio.run(sender.broadcast(bot, [1, 2, 3], "текст", parse_mode=None))
    assert (sent, failed) == (2, 1)
    assert sleeps == [sender.PACE] * 3
    assert all(call.parse_mode is None for call in bot.sent)


def test_broadcast_can_be_cancelled(make_bot, sleeps):
    cancel = asyncio.Event()
    bot = make_bot()

    async def scenario():
        original = sender.safe_send

        async def wrapped(*args, **kwargs):
            result = await original(*args, **kwargs)
            cancel.set()  # отмена после первого сообщения
            return result

        sender.safe_send = wrapped
        try:
            return await sender.broadcast(bot, [1, 2, 3, 4], "текст", cancel=cancel)
        finally:
            sender.safe_send = original

    sent, failed = asyncio.run(scenario())
    assert (sent, failed) == (1, 0)
    assert len(bot.sent) == 1
