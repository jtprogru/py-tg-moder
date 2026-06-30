import asyncio

import pytest

import handlers.admin_handlers as admin
from core.storage import Storage


class FakeUser:
    def __init__(self, user_id, is_bot=False):
        self.id = user_id
        self.is_bot = is_bot


class FakeAdmin:
    def __init__(self, user):
        self.user = user


class FakeMessage:
    def __init__(self, reply_to=None, message_id=1):
        self.reply_to_message = reply_to
        self.from_user = None
        self.message_id = message_id
        self.replies = []
        self.deleted = False

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)

    async def delete(self):
        self.deleted = True


class FakeChat:
    def __init__(self, chat_id, admins):
        self.id = chat_id
        self._admins = admins
        self.banned = []
        self.restricted = []

    async def get_administrators(self):
        return self._admins

    async def ban_member(self, user_id, until_date=None):
        self.banned.append((user_id, until_date))

    async def restrict_member(self, user_id, permissions, until_date=None):
        self.restricted.append((user_id, until_date))


class FakeContext:
    class _Bot:
        id = 999

    def __init__(self, args=None):
        self.bot = self._Bot()
        self.args = args or []


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(admin, "get_storage", lambda: s)
    yield s
    s.close()


def _make(args, issuer_id=5):
    command = FakeMessage(reply_to=None, message_id=101)
    chat = FakeChat(100, [FakeAdmin(FakeUser(issuer_id))])
    update = FakeUpdate(command, chat, FakeUser(issuer_id))
    return update, command, chat, FakeContext(args=args)


def test_ban_by_numeric_id(store):
    update, command, chat, ctx = _make(["123456"])
    asyncio.run(admin.ban_user(update, ctx))
    assert chat.banned == [(123456, None)]


def test_ban_by_username(store):
    store.remember_user(42, "spammer")
    update, command, chat, ctx = _make(["@spammer"])
    asyncio.run(admin.ban_user(update, ctx))
    assert chat.banned == [(42, None)]


def test_ban_by_username_with_duration(store):
    store.remember_user(42, "spammer")
    update, command, chat, ctx = _make(["@spammer", "1d"])
    asyncio.run(admin.ban_user(update, ctx))
    user_id, until = chat.banned[0]
    assert user_id == 42 and until is not None


def test_unknown_username_is_reported(store):
    update, command, chat, ctx = _make(["@ghost"])
    asyncio.run(admin.ban_user(update, ctx))
    assert chat.banned == []
    assert any("Не нашёл" in r for r in command.replies)


def test_no_target_at_all_is_reported(store):
    update, command, chat, ctx = _make([])
    asyncio.run(admin.ban_user(update, ctx))
    assert chat.banned == []
    assert any("Укажи цель" in r for r in command.replies)


def test_mute_by_username_persists(store):
    store.remember_user(42, "spammer")
    update, command, chat, ctx = _make(["@spammer", "30m"])
    asyncio.run(admin.mute_user(update, ctx))
    assert chat.restricted and chat.restricted[0][0] == 42
    assert store.is_muted(100, 42, now=0) is True


def test_protect_admin_target_by_id(store):
    # id 5 is the issuing admin; targeting them must be refused.
    update, command, chat, ctx = _make(["5"])
    asyncio.run(admin.ban_user(update, ctx))
    assert chat.banned == []
    assert any("администратор" in r.lower() for r in command.replies)
