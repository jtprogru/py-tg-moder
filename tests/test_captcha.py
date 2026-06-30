import asyncio

import pytest

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
    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeChat:
    def __init__(self, chat_id=100):
        self.id = chat_id
        self.restricted = []  # (user_id, permissions)
        self.banned = []
        self.unbanned = []
        self.sent = []

    async def restrict_member(self, user_id, permissions):
        self.restricted.append((user_id, permissions))

    async def ban_member(self, user_id):
        self.banned.append(user_id)

    async def unban_member(self, user_id):
        self.unbanned.append(user_id)

    async def send_message(self, text, **kwargs):
        msg = FakeMessage()
        self.sent.append(text)
        return msg


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
    assert captcha._key(100, 42) in captcha._pending
    assert store.is_muted(100, 42, now=10**9) is True


def test_pass_unmutes_and_welcomes(store):
    chat = FakeChat()
    store.add_mute(100, 42, until=None)
    captcha._pending[captcha._key(100, 42)] = FakeMessage()
    query = FakeQuery("captcha:42", FakeUser(42))
    asyncio.run(captcha.captcha_callback(FakeUpdate(chat, query), None))

    assert chat.restricted and chat.restricted[0] == (42, captcha.UNMUTE_PERMISSIONS)
    assert captcha._key(100, 42) not in captcha._pending
    assert store.is_muted(100, 42, now=0) is False
    assert chat.sent  # welcome posted
    assert query.answers  # popup answered


def test_wrong_user_cannot_pass(store):
    chat = FakeChat()
    captcha._pending[captcha._key(100, 42)] = FakeMessage()
    query = FakeQuery("captcha:42", FakeUser(7))  # someone else taps
    asyncio.run(captcha.captcha_callback(FakeUpdate(chat, query), None))

    assert chat.restricted == []  # not unmuted
    assert captcha._key(100, 42) in captcha._pending  # still pending
    assert any("не для тебя" in (a or "") for a in query.answers)


def test_expire_kicks_when_unsolved(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "kick")
    chat = FakeChat()
    challenge = FakeMessage()
    captcha._pending[captcha._key(100, 42)] = challenge
    asyncio.run(captcha._expire(chat, 42))

    assert chat.banned == [42] and chat.unbanned == [42]  # kick = ban + unban
    assert challenge.deleted is True
    assert captcha._key(100, 42) not in captcha._pending


def test_expire_bans_when_configured(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "ban")
    chat = FakeChat()
    captcha._pending[captcha._key(100, 42)] = FakeMessage()
    asyncio.run(captcha._expire(chat, 42))
    assert chat.banned == [42] and chat.unbanned == []


def test_expire_noop_when_already_passed(store, monkeypatch):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 0)
    chat = FakeChat()
    asyncio.run(captcha._expire(chat, 42))  # nothing pending
    assert chat.banned == []
