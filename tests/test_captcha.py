import asyncio

import pytest
from telegram.error import TelegramError

import handlers.captcha as captcha
from core import config
from core.storage import Storage


class _DummyTask:
    def add_done_callback(self, cb):
        pass


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id

    def mention_html(self):
        return f"user:{self.id}"


class FakeMessage:
    def __init__(self, message_id=999):
        self.message_id = message_id


class FakeChat:
    def __init__(self, chat_id=100):
        self.id = chat_id
        self.restricted = []  # (user_id, permissions)
        self.banned = []
        self.unbanned = []
        self.sent = []
        self.deleted_messages = []

    async def restrict_member(self, user_id, permissions):
        self.restricted.append((user_id, permissions))

    async def ban_member(self, user_id):
        self.banned.append(user_id)

    async def unban_member(self, user_id):
        self.unbanned.append(user_id)

    async def send_message(self, text, **kwargs):
        self.sent.append(text)
        return FakeMessage(message_id=555)

    async def delete_message(self, message_id):
        self.deleted_messages.append(message_id)


class FakeBot:
    def __init__(self, chats):
        self._chats = {c.id: c for c in chats}

    async def get_chat(self, chat_id):
        chat = self._chats.get(chat_id)
        if chat is None:
            raise TelegramError(f"chat {chat_id} not found")
        return chat


class FakeApp:
    def __init__(self, bot):
        self.bot = bot


class FakeQuery:
    def __init__(self, data, from_user):
        self.data = data
        self.from_user = from_user
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)


class FakeUpdate:
    def __init__(self, chat, query):
        self.effective_chat = chat
        self.callback_query = query


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(captcha, "get_storage", lambda: s)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def clear_pending():
    captcha._pending.clear()
    yield
    captcha._pending.clear()


@pytest.fixture
def no_scheduling(monkeypatch):
    # Don't actually schedule the expiry task during start_challenge tests.
    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr(captcha.asyncio, "create_task", _fake_create_task)


def test_start_challenge_mutes_and_prompts(store, no_scheduling):
    chat = FakeChat()
    asyncio.run(captcha.start_challenge(chat, FakeUser(42)))
    assert chat.restricted and chat.restricted[0] == (42, captcha.MUTE_PERMISSIONS)
    assert chat.sent  # captcha prompt posted
    assert captcha._pending[captcha._key(100, 42)] == 555  # tracks the challenge message id
    assert store.is_muted(100, 42, now=10**9) is True
    # The challenge is persisted so it can be rearmed after a restart.
    assert [(c["chat_id"], c["user_id"], c["message_id"]) for c in store.list_captchas()] == [(100, 42, 555)]


def test_pass_unmutes_and_welcomes(store):
    chat = FakeChat()
    store.add_mute(100, 42, until=None)
    store.add_captcha(100, 42, message_id=555, deadline=10**9)
    captcha._pending[captcha._key(100, 42)] = 555
    query = FakeQuery("captcha:42", FakeUser(42))
    asyncio.run(captcha.captcha_callback(FakeUpdate(chat, query), None))

    assert chat.restricted and chat.restricted[0] == (42, captcha.UNMUTE_PERMISSIONS)
    assert captcha._key(100, 42) not in captcha._pending
    assert 555 in chat.deleted_messages  # challenge removed
    assert store.is_muted(100, 42, now=0) is False
    assert store.list_captchas() == []  # persisted challenge cleared
    assert chat.sent  # welcome posted
    assert query.answers  # popup answered


def test_wrong_user_cannot_pass(store):
    chat = FakeChat()
    captcha._pending[captcha._key(100, 42)] = 555
    query = FakeQuery("captcha:42", FakeUser(7))  # someone else taps
    asyncio.run(captcha.captcha_callback(FakeUpdate(chat, query), None))

    assert chat.restricted == []  # not unmuted
    assert captcha._key(100, 42) in captcha._pending  # still pending
    assert any("не для тебя" in (a or "") for a in query.answers)


def test_expire_kicks_when_unsolved(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "kick")
    chat = FakeChat()
    store.add_captcha(100, 42, message_id=555, deadline=0)
    captcha._pending[captcha._key(100, 42)] = 555
    asyncio.run(captcha._expire(chat, 42))

    assert chat.banned == [42] and chat.unbanned == [42]  # kick = ban + unban
    assert 555 in chat.deleted_messages
    assert captcha._key(100, 42) not in captcha._pending
    assert store.list_captchas() == []  # persisted challenge cleared


def test_expire_bans_when_configured(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "ban")
    chat = FakeChat()
    captcha._pending[captcha._key(100, 42)] = 555
    asyncio.run(captcha._expire(chat, 42))
    assert chat.banned == [42] and chat.unbanned == []


def test_expire_noop_when_already_passed(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    chat = FakeChat()
    asyncio.run(captcha._expire(chat, 42))  # nothing pending
    assert chat.banned == []


def test_rearm_reschedules_pending(store, monkeypatch):
    monkeypatch.setattr(captcha.time, "time", lambda: 1000)
    calls = []

    async def _record(chat, user_id, delay=None):
        calls.append((chat.id, user_id, delay))

    monkeypatch.setattr(captcha, "_expire", _record)
    store.add_captcha(100, 42, message_id=555, deadline=1030)
    chat = FakeChat()

    async def _run():
        await captcha.rearm_captchas(FakeApp(FakeBot([chat])))
        await asyncio.sleep(0)  # let the scheduled recorder run

    asyncio.run(_run())

    assert captcha._pending[captcha._key(100, 42)] == 555
    assert calls == [(100, 42, 30)]  # remaining time until the deadline


def test_rearm_clamps_expired_deadline_to_zero(store, monkeypatch):
    monkeypatch.setattr(captcha.time, "time", lambda: 5000)
    calls = []

    async def _record(chat, user_id, delay=None):
        calls.append((chat.id, user_id, delay))

    monkeypatch.setattr(captcha, "_expire", _record)
    store.add_captcha(100, 42, message_id=555, deadline=1030)  # already past

    async def _run():
        await captcha.rearm_captchas(FakeApp(FakeBot([FakeChat()])))
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert calls == [(100, 42, 0)]  # never negative


def test_rearm_drops_unreachable_chat(store):
    store.add_captcha(777, 42, message_id=555, deadline=10**9)

    async def _run():
        await captcha.rearm_captchas(FakeApp(FakeBot([])))  # bot can't reach chat 777
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert captcha._key(777, 42) not in captcha._pending
    assert store.list_captchas() == []  # stale row removed
