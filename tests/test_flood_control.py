import asyncio

import pytest

import handlers.flood_control as flood
from core import config
from core.storage import Storage

# -- FloodTracker (pure) ---------------------------------------------------


def test_tracker_under_limit():
    t = flood.FloodTracker(limit=3, window=10)
    assert t.record("k", now=1.0) is False
    assert t.record("k", now=1.1) is False
    assert t.record("k", now=1.2) is False  # 3 == limit, not over


def test_tracker_over_limit():
    t = flood.FloodTracker(limit=3, window=10)
    for i in range(3):
        t.record("k", now=1.0 + i)
    assert t.record("k", now=1.5) is True  # 4th within window > limit


def test_tracker_window_slides():
    t = flood.FloodTracker(limit=2, window=10)
    t.record("k", now=0.0)
    t.record("k", now=1.0)
    # 20s later the old events have aged out of the window.
    assert t.record("k", now=21.0) is False


def test_tracker_keys_are_independent():
    t = flood.FloodTracker(limit=1, window=10)
    t.record("a", now=1.0)
    assert t.record("b", now=1.0) is False


def test_tracker_reset():
    t = flood.FloodTracker(limit=1, window=10)
    t.record("k", now=1.0)
    t.reset("k")
    assert t.record("k", now=1.1) is False


# -- flood_control handler -------------------------------------------------


class FakeUser:
    def __init__(self, user_id, is_bot=False):
        self.id = user_id
        self.is_bot = is_bot

    def mention_html(self):
        return f"user:{self.id}"


class FakeAdmin:
    def __init__(self, user):
        self.user = user


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_html(self, text, **kwargs):
        self.replies.append(text)


class FakeChat:
    def __init__(self, chat_id, admins=()):
        self.id = chat_id
        self._admins = list(admins)
        self.restricted = []  # list of (user_id, until_date)

    async def get_administrators(self):
        return self._admins

    async def restrict_member(self, user_id, permissions, until_date=None):
        self.restricted.append((user_id, until_date))


class FakeContext:
    class _Bot:
        id = 999

    bot = _Bot()


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(flood, "get_storage", lambda: s)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def small_tracker(monkeypatch):
    monkeypatch.setattr(flood, "_tracker", flood.FloodTracker(limit=2, window=100))
    monkeypatch.setattr(config, "FLOOD_MUTE_SECONDS", 60)


def _send(chat, user_id=42):
    msg = FakeMessage()
    update = FakeUpdate(msg, chat, FakeUser(user_id))
    asyncio.run(flood.flood_control(update, FakeContext()))
    return msg


def test_flood_triggers_temporary_mute(store):
    chat = FakeChat(100)
    _send(chat)
    _send(chat)
    msg = _send(chat)  # 3rd > limit 2 -> mute
    assert len(chat.restricted) == 1
    user_id, until = chat.restricted[0]
    assert user_id == 42
    assert until is not None and until > 0  # temporary mute with until_date
    assert store.is_muted(100, 42, now=0) is True
    assert store.get_counter(100, "flood_muted") == 1
    assert any("флуд" in r for r in msg.replies)


def test_no_mute_under_limit(store):
    chat = FakeChat(100)
    _send(chat)
    _send(chat)
    assert chat.restricted == []


def test_admin_is_not_muted(store):
    chat = FakeChat(100, admins=[FakeAdmin(FakeUser(42))])
    _send(chat)
    _send(chat)
    _send(chat)
    assert chat.restricted == []


def test_bot_messages_ignored(store):
    chat = FakeChat(100)
    for _ in range(5):
        msg = FakeMessage()
        update = FakeUpdate(msg, chat, FakeUser(42, is_bot=True))
        asyncio.run(flood.flood_control(update, FakeContext()))
    assert chat.restricted == []
