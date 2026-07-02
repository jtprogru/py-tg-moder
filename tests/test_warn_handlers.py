import asyncio

import pytest

import handlers.warn_handlers as warns
from core.storage import Storage


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
    def __init__(self, reply_to=None):
        self.reply_to_message = reply_to
        self.from_user = None
        self.replies = []
        self.deleted = False

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)

    async def reply_html(self, text, **kwargs):
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

    async def ban_member(self, user_id):
        self.banned.append(user_id)

    async def restrict_member(self, user_id, permissions):
        self.restricted.append(user_id)


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
    monkeypatch.setattr(warns, "get_storage", lambda: s)
    yield s
    s.close()


def _make(target, issuer_id=5, args=None):
    spam = FakeMessage()
    spam.from_user = target
    command = FakeMessage(reply_to=spam)
    chat = FakeChat(100, [FakeAdmin(FakeUser(issuer_id))])
    update = FakeUpdate(command, chat, FakeUser(issuer_id))
    return update, command, chat, FakeContext(args=args)


def test_warn_increments_confirms_and_cleans(store, monkeypatch):
    monkeypatch.setattr(warns, "WARN_LIMIT", 3)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target, args=["спам"])
    asyncio.run(warns.warn_user(update, ctx))

    assert store.count_warns(100, 42) == 1
    assert any("(1/3)" in r for r in command.replies)
    assert any("спам" in r for r in command.replies)
    assert command.deleted is True
    assert chat.restricted == [] and chat.banned == []


def test_warn_reaches_limit_mutes_and_resets(store, monkeypatch):
    monkeypatch.setattr(warns, "WARN_LIMIT", 2)
    monkeypatch.setattr(warns, "WARN_ACTION", "mute")
    target = FakeUser(42)

    update1, _, chat, ctx = _make(target)
    asyncio.run(warns.warn_user(update1, ctx))
    update2, command2, chat2, ctx2 = _make(target)
    asyncio.run(warns.warn_user(update2, ctx2))

    assert chat2.restricted == [42]
    assert store.count_warns(100, 42) == 0  # counter reset after punishment
    assert store.is_muted(100, 42, now=10**9) is True  # mute persisted
    assert any("замьючен" in r for r in command2.replies)


def test_warn_reaches_limit_bans(store, monkeypatch):
    monkeypatch.setattr(warns, "WARN_LIMIT", 1)
    monkeypatch.setattr(warns, "WARN_ACTION", "ban")
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.warn_user(update, ctx))
    assert chat.banned == [42]
    assert any("забанен" in r for r in command.replies)


def test_warns_list_shows_history(store):
    store.add_warn(100, 42, moderator_id=5, reason="спам", now=1700000000)
    store.add_warn(100, 42, moderator_id=5, reason="флуд", now=1700100000)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.warns_list(update, ctx))
    out = command.replies[0]
    assert "спам" in out and "флуд" in out


def test_warns_list_empty(store):
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.warns_list(update, ctx))
    assert "нет предупреждений" in command.replies[0]


def test_warn_reason_html_is_escaped(store, monkeypatch):
    # The reason is admin-provided and rendered into an HTML message; any markup
    # in it must be escaped so it can't inject formatting/links into the reply.
    monkeypatch.setattr(warns, "WARN_LIMIT", 3)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target, args=["<b>evil</b>"])
    asyncio.run(warns.warn_user(update, ctx))
    out = "\n".join(command.replies)
    assert "&lt;b&gt;evil&lt;/b&gt;" in out
    assert "<b>evil</b>" not in out


def test_warns_list_reason_html_is_escaped(store):
    # Stored reasons are echoed back into an HTML message and must be escaped too.
    store.add_warn(100, 42, moderator_id=5, reason="<i>x</i>", now=1700000000)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.warns_list(update, ctx))
    out = command.replies[0]
    assert "&lt;i&gt;x&lt;/i&gt;" in out
    assert "<i>x</i>" not in out


def test_unwarn_removes_last(store):
    store.add_warn(100, 42, now=1700000000)
    store.add_warn(100, 42, now=1700100000)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.unwarn_user(update, ctx))
    assert store.count_warns(100, 42) == 1
    assert any("Осталось: 1" in r for r in command.replies)
    assert command.deleted is True


def test_unwarn_when_none(store):
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.unwarn_user(update, ctx))
    assert "нет предупреждений" in command.replies[0]


# -- audit trail -------------------------------------------------------------


def test_warn_records_audit_event(store, audit_store, monkeypatch):
    monkeypatch.setattr(warns, "WARN_LIMIT", 3)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target, args=["спам"])
    asyncio.run(warns.warn_user(update, ctx))
    events = audit_store.list_audit_events(chat_id=100)
    assert [e["event"] for e in events] == ["warn"]
    assert events[0]["user_id"] == 42
    assert events[0]["actor_id"] == 5
    assert events[0]["reason"] == "спам"


def test_auto_punish_records_full_audit_trail(store, audit_store, monkeypatch):
    monkeypatch.setattr(warns, "WARN_LIMIT", 1)
    monkeypatch.setattr(warns, "WARN_ACTION", "mute")
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.warn_user(update, ctx))
    # Newest first: the warn itself, then the punishment, then the reset.
    events = [e["event"] for e in audit_store.list_audit_events(chat_id=100)]
    assert events == ["warns_cleared", "auto_mute", "warn"]
    # History survives the reset even though the live counter is back to zero.
    assert store.count_warns(100, 42) == 0
    assert len(store.list_warns(100, 42, include_deleted=True)) == 1


def test_unwarn_records_audit_event(store, audit_store):
    store.add_warn(100, 42, now=1700000000)
    target = FakeUser(42)
    update, command, chat, ctx = _make(target)
    asyncio.run(warns.unwarn_user(update, ctx))
    events = audit_store.list_audit_events(chat_id=100, event="unwarn")
    assert len(events) == 1
    assert events[0]["user_id"] == 42
