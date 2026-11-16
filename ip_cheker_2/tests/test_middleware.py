import asyncio

from aiogram.types import User

from middlewares.users import UserMiddleware
from utils import storage


async def handler(event, data):
    return "handled"


def call(middleware, data):
    return asyncio.run(middleware(handler, None, data))


def test_new_user_is_registered(data):
    middleware = UserMiddleware()
    result = call(middleware, {"event_from_user": User(id=7, is_bot=False, first_name="A", username="a")})
    assert result == "handled"
    assert "7" in storage.all_users()
    assert storage.all_users()["7"]["username"] == "a"


def test_known_user_does_not_touch_disk(data, monkeypatch):
    writes = []
    original = storage.run

    def counted(sql, params=()):
        writes.append(sql.split()[0])
        return original(sql, params)

    monkeypatch.setattr(storage, "run", counted)
    middleware = UserMiddleware()
    user = User(id=7, is_bot=False, first_name="A")
    call(middleware, {"event_from_user": user})
    call(middleware, {"event_from_user": user})
    call(middleware, {"event_from_user": user})
    assert writes == ["INSERT"]  # один INSERT на нового, ноль на повторных


def test_update_without_user_passes_through(data):
    assert call(UserMiddleware(), {}) == "handled"
    assert storage.all_users() == {}


def test_other_bots_are_not_registered(data):
    call(UserMiddleware(), {"event_from_user": User(id=9, is_bot=True, first_name="Bot")})
    assert storage.all_users() == {}


def test_storage_failure_does_not_break_update(data, monkeypatch):
    async def broken(uid, username):
        raise OSError("диск кончился")

    monkeypatch.setattr(storage, "register_user", broken)
    assert call(UserMiddleware(), {"event_from_user": User(id=7, is_bot=False, first_name="A")}) == "handled"
