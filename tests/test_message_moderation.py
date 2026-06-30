import asyncio

import pytest
from telegram import MessageEntity

import handlers.message_moderation as mod
import handlers.warn_handlers as warns
from core import config
from core.storage import Storage


class FakeMessage:
    def __init__(self, text="", entities=None, caption=None, caption_entities=None, forward_origin=None):
        self.text = text
        self.caption = caption
        self.entities = entities or []
        self.caption_entities = caption_entities or []
        self.forward_origin = forward_origin
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeUser:
    def __init__(self, user_id, is_bot=False):
        self.id = user_id
        self.is_bot = is_bot

    def mention_html(self):
        return f"user:{self.id}"


class FakeAdmin:
    def __init__(self, user):
        self.user = user


class FakeChat:
    def __init__(self, chat_id, admins=()):
        self.id = chat_id
        self._admins = list(admins)
        self.restricted = []
        self.banned = []

    async def get_administrators(self):
        return self._admins

    async def restrict_member(self, user_id, permissions):
        self.restricted.append(user_id)

    async def ban_member(self, user_id):
        self.banned.append(user_id)


class FakeContext:
    class _Bot:
        id = 999

    bot = _Bot()


class FakeUpdate:
    def __init__(self, message, chat, user, edited=False):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user
        self.edited_message = message if edited else None


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(mod, "get_storage", lambda: s)
    monkeypatch.setattr(warns, "get_storage", lambda: s)
    yield s
    s.close()


# -- find_violation (pure) -------------------------------------------------


def test_violation_plain_link():
    msg = FakeMessage(text="http://spam.com", entities=[MessageEntity(type=MessageEntity.URL, offset=0, length=15)])
    assert mod.find_violation(msg) == "ссылка"


def test_violation_telegram_invite():
    msg = FakeMessage(text="join", entities=[MessageEntity(type=MessageEntity.TEXT_LINK, offset=0, length=4, url="https://t.me/+abcd")])
    assert mod.find_violation(msg) == "telegram-инвайт"


def test_violation_mention():
    msg = FakeMessage(text="@someone hi", entities=[MessageEntity(type=MessageEntity.MENTION, offset=0, length=8)])
    assert mod.find_violation(msg) == "@-упоминание"


def test_violation_forward():
    msg = FakeMessage(text="hello", forward_origin=object())
    assert mod.find_violation(msg) == "форвард"


def test_no_violation_clean_text():
    assert mod.find_violation(FakeMessage(text="просто привет всем")) is None


def test_link_filter_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "NEWCOMER_BLOCK_LINKS", False)
    msg = FakeMessage(text="http://spam.com", entities=[MessageEntity(type=MessageEntity.URL, offset=0, length=15)])
    assert mod.find_violation(msg) is None


# -- moderate_message ------------------------------------------------------


def _link_msg():
    return FakeMessage(text="http://spam.com", entities=[MessageEntity(type=MessageEntity.URL, offset=0, length=15)])


def test_newcomer_link_is_deleted(store, monkeypatch):
    monkeypatch.setattr(config, "NEWCOMER_ACTION", "delete")
    msg = _link_msg()
    update = FakeUpdate(msg, FakeChat(100), FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert msg.deleted is True
    assert store.get_counter(100, "newcomer_filtered") == 1


def test_established_user_is_not_filtered(store):
    # Push the user past the newcomer threshold first.
    for ts in range(config.NEWCOMER_MAX_MESSAGES):
        store.touch_member(100, 42, now=1000 + ts)
    msg = _link_msg()
    update = FakeUpdate(msg, FakeChat(100), FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert msg.deleted is False


def test_clean_message_counts_but_is_kept(store):
    msg = FakeMessage(text="всем привет")
    update = FakeUpdate(msg, FakeChat(100), FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert msg.deleted is False
    assert store.get_member(100, 42)["message_count"] == 1


def test_admin_newcomer_is_not_filtered(store):
    msg = _link_msg()
    chat = FakeChat(100, admins=[FakeAdmin(FakeUser(42))])
    update = FakeUpdate(msg, chat, FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert msg.deleted is False


def test_edited_message_is_rechecked(store):
    # User sends one clean message (counts as a newcomer message)...
    clean = FakeMessage(text="привет")
    asyncio.run(mod.moderate_message(FakeUpdate(clean, FakeChat(100), FakeUser(42)), FakeContext()))
    # ...then edits a message into spam: the edit must be caught and not double-counted.
    spam = _link_msg()
    asyncio.run(mod.moderate_message(FakeUpdate(spam, FakeChat(100), FakeUser(42), edited=True), FakeContext()))
    assert spam.deleted is True
    assert store.get_member(100, 42)["message_count"] == 1


def test_action_mute_restricts_and_persists(store, monkeypatch):
    monkeypatch.setattr(config, "NEWCOMER_ACTION", "mute")
    msg = _link_msg()
    chat = FakeChat(100)
    update = FakeUpdate(msg, chat, FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert msg.deleted is True
    assert chat.restricted == [42]
    assert store.is_muted(100, 42, now=10**9) is True


def test_action_warn_escalates_at_limit(store, monkeypatch):
    monkeypatch.setattr(config, "NEWCOMER_ACTION", "warn")
    monkeypatch.setattr(config, "WARN_LIMIT", 1)
    monkeypatch.setattr(warns, "WARN_ACTION", "mute")
    msg = _link_msg()
    chat = FakeChat(100)
    update = FakeUpdate(msg, chat, FakeUser(42))
    asyncio.run(mod.moderate_message(update, FakeContext()))
    assert chat.restricted == [42]  # escalated via warn limit
    assert store.count_warns(100, 42) == 0  # reset after escalation
