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
        self.banned = []  # (user_id, until_date)
        self.unbanned = []
        self.restricted = []  # (user_id, until_date)

    async def get_administrators(self):
        return self._admins

    async def ban_member(self, user_id, until_date=None):
        self.banned.append((user_id, until_date))

    async def unban_member(self, user_id):
        self.unbanned.append(user_id)

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


def _make(target_id=42, issuer_id=5, args=None):
    spam = FakeMessage(message_id=100)
    spam.from_user = FakeUser(target_id)
    command = FakeMessage(reply_to=spam, message_id=101)
    chat = FakeChat(100, [FakeAdmin(FakeUser(issuer_id))])
    update = FakeUpdate(command, chat, FakeUser(issuer_id))
    return update, command, chat, FakeContext(args=args)


def test_temporary_mute_sets_until_and_persists(store):
    update, command, chat, ctx = _make(args=["30m"])
    asyncio.run(admin.mute_user(update, ctx))
    user_id, until = chat.restricted[0]
    assert user_id == 42 and until is not None
    assert store.is_muted(100, 42, now=0) is True
    assert any("30 мин" in r for r in command.replies)


def test_permanent_mute_without_duration(store):
    update, command, chat, ctx = _make(args=[])
    asyncio.run(admin.mute_user(update, ctx))
    _, until = chat.restricted[0]
    assert until is None
    assert store.is_muted(100, 42, now=10**9) is True


def test_temporary_ban_sets_until(store):
    update, command, chat, ctx = _make(args=["1d"])
    asyncio.run(admin.ban_user(update, ctx))
    user_id, until = chat.banned[0]
    assert user_id == 42 and until is not None


def test_unmute_clears_persisted_mute(store):
    store.add_mute(100, 42, until=None)
    update, command, chat, ctx = _make(args=[])
    asyncio.run(admin.unmute_user(update, ctx))
    assert store.is_muted(100, 42, now=0) is False


def test_kick_bans_then_unbans(store):
    update, command, chat, ctx = _make()
    asyncio.run(admin.kick_user(update, ctx))
    assert [uid for uid, _ in chat.banned] == [42]
    assert chat.unbanned == [42]
    assert command.deleted is True
