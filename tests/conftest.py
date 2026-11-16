"""Обвязка тестов: изолированная DATA_DIR, фейковый Bot, фабрики апдейтов.

Telegram не нужен: FakeBot — настоящий aiogram.Bot с переопределённым __call__,
через который проходят ВСЕ методы API. Сети нет, вызовы записываются.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# config читает окружение при импорте — подменяем ДО его импорта.
os.environ["ENV_FILE"] = str(ROOT / "tests" / "_no_such_file.env")
os.environ["TOKEN"] = "42:TEST"
os.environ["ADMIN_ID"] = "1"
os.environ["ALERT_CHAT_ID"] = "-1001"
os.environ["ALERT_THREAD_ID"] = "77"
os.environ["PROXY_URL"] = ""
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ipcheker-tests-")

import pytest  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

import config  # noqa: E402
from utils import storage  # noqa: E402


class FakeBot(Bot):
    def __init__(self, failures: dict | None = None):
        super().__init__("42:TEST")
        self.calls: list = []
        self.failures = {name: list(items) for name, items in (failures or {}).items()}
        self._mid = 100

    async def __call__(self, method, request_timeout=None):
        name = type(method).__name__
        self.calls.append(method)
        queue = self.failures.get(name)
        if queue:
            exc = queue.pop(0)
            if exc is not None:
                raise exc
        if name == "GetMe":
            return User(id=42, is_bot=True, first_name="TestBot", username="test_bot")
        if name in ("SendMessage", "EditMessageText", "SendDocument"):
            self._mid += 1
            return Message(
                message_id=self._mid,
                date=datetime.now(),
                chat=Chat(id=getattr(method, "chat_id", 1) or 1, type="private"),
                text=getattr(method, "text", None) or "",
            )
        return True

    def of(self, name: str) -> list:
        return [call for call in self.calls if type(call).__name__ == name]

    @property
    def sent(self) -> list:
        return self.of("SendMessage")

    @property
    def edits(self) -> list:
        return self.of("EditMessageText")

    @property
    def documents(self) -> list:
        return self.of("SendDocument")

    def texts(self) -> list[str]:
        return [call.text for call in self.sent]


def _user(uid: int) -> User:
    return User(id=uid, is_bot=False, first_name="Test", username=f"u{uid}")


def message_update(
    text: str, uid: int = 1, chat_id: int | None = None, message_id: int = 1,
    thread_id: int | None = None, chat_type: str = "private",
) -> Update:
    """thread_id + chat_type='supergroup' — сообщение из темы супергруппы."""
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id,
            date=datetime.now(),
            chat=Chat(id=chat_id if chat_id is not None else uid, type=chat_type),
            from_user=_user(uid),
            text=text,
            message_thread_id=thread_id,
            is_topic_message=True if thread_id else None,
        ),
    )


def callback_update(
    data: str, uid: int = 1, chat_id: int | None = None, message_id: int = 1,
    thread_id: int | None = None, chat_type: str = "private",
) -> Update:
    return Update(
        update_id=1000 + message_id,
        callback_query=CallbackQuery(
            id=str(message_id),
            from_user=_user(uid),
            chat_instance="0",
            data=data,
            message=Message(
                message_id=message_id,
                date=datetime.now(),
                chat=Chat(id=chat_id if chat_id is not None else uid, type=chat_type),
                from_user=_user(uid),
                text="меню",
                message_thread_id=thread_id,
                is_topic_message=True if thread_id else None,
            ),
        ),
    )


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Каждый тест получает свою папку данных."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "bot.db")
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(config, "LOG_FILE", tmp_path / "logs" / "bot.log")
    monkeypatch.setattr(config, "LEGACY_FILES", {
        kind: tmp_path / f"{kind}.json" for kind in ("users", "history", "tracked", "settings")
    })
    storage.close()
    storage.init()
    yield tmp_path
    storage.close()
    storage.KNOWN_USERS.clear()


@pytest.fixture(autouse=True)
def clean_runtime():
    from handlers import admin, scan

    scan.BUSY.clear()
    scan.CANCELS.clear()
    admin.BC_CANCEL.clear()
    yield
    scan.BUSY.clear()
    scan.CANCELS.clear()
    admin.BC_CANCEL.clear()


@pytest.fixture(scope="session")
def dp():
    """Один Dispatcher на сессию — как в продакшене.

    Роутеры aiogram подключаются к диспетчеру один раз, поэтому пересоздавать
    Dispatcher в каждом тесте нельзя: это ошибка архитектуры, а не теста.
    """
    import main as app

    return app.build_dispatcher()


@pytest.fixture(autouse=True)
def fresh_fsm(dp):
    """Состояния FSM не должны протекать между тестами."""
    dp.fsm.storage.storage.clear()
    yield
    dp.fsm.storage.storage.clear()


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def make_bot():
    def factory(failures=None):
        return FakeBot(failures)

    return factory


@pytest.fixture
def sleeps(monkeypatch):
    """Записывает паузы вместо реального ожидания."""
    recorded: list[float] = []

    async def fake_sleep(delay, *args, **kwargs):
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return recorded


@pytest.fixture
def track():
    """Посев списка мониторинга: {uid: [(ip, status), ...]}."""
    def _track(mapping):
        async def scenario():
            for uid, items in mapping.items():
                for ip, status in items:
                    await storage.add_tracked(int(uid), ip)
                    await storage.save_tracked({str(uid): [{"ip": ip, "status": status}]})
        asyncio.run(scenario())
    return _track


@pytest.fixture
def msg():
    return message_update


@pytest.fixture
def cb():
    return callback_update
