import asyncio
from types import SimpleNamespace

import pytest

import handlers.user_handlers as user_handlers
from core import config
from core.storage import Storage


class FakeUser:
    def __init__(self, uid, username=None):
        self.id = uid
        self.username = username

    def mention_html(self):
        return f"user:{self.id}"


class FakeChat:
    def __init__(self, chat_id=100):
        self.id = chat_id
        self.banned = []
        self.sent = []

    async def ban_member(self, user_id):
        self.banned.append(user_id)

    async def send_message(self, text, **kwargs):
        self.sent.append(text)


def _update(chat, user):
    member = SimpleNamespace(new_chat_member=SimpleNamespace(user=user))
    return SimpleNamespace(effective_chat=chat, chat_member=member)


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(user_handlers, "get_storage", lambda: s)
    yield s
    s.close()


@pytest.fixture
def joined(monkeypatch):
    # Pretend the status change is "joined the chat".
    monkeypatch.setattr(user_handlers, "extract_status_change", lambda _cm: (False, True))


@pytest.fixture
def captured_challenge(monkeypatch):
    calls = []

    async def _fake_start(chat, user):
        calls.append((chat.id, user.id))

    monkeypatch.setattr(user_handlers, "start_challenge", _fake_start)
    return calls


def _set_cas(monkeypatch, listed):
    monkeypatch.setattr(user_handlers.casapi, "check", lambda user_id: {"ok": listed})


def test_cas_hit_bans_without_captcha(store, joined, captured_challenge, monkeypatch):
    _set_cas(monkeypatch, listed=True)
    chat = FakeChat()
    asyncio.run(user_handlers.greet_chat_members(_update(chat, FakeUser(42, "spammer")), None))

    assert chat.banned == [42]
    assert captured_challenge == []  # CAS hit skips the captcha
    assert chat.sent == []  # and no welcome
    # The joiner is still recorded and their @username cached.
    assert store.resolve_username("spammer") == 42
    assert store.get_member(100, 42) is not None


def test_clean_user_gets_captcha(store, joined, captured_challenge, monkeypatch):
    _set_cas(monkeypatch, listed=False)
    monkeypatch.setattr(config, "CAPTCHA_ENABLED", True)
    chat = FakeChat()
    asyncio.run(user_handlers.greet_chat_members(_update(chat, FakeUser(7, "alice")), None))

    assert chat.banned == []
    assert captured_challenge == [(100, 7)]
    assert chat.sent == []  # welcome is posted only after the captcha passes


def test_clean_user_greeted_when_captcha_disabled(store, joined, captured_challenge, monkeypatch):
    _set_cas(monkeypatch, listed=False)
    monkeypatch.setattr(config, "CAPTCHA_ENABLED", False)
    chat = FakeChat()
    asyncio.run(user_handlers.greet_chat_members(_update(chat, FakeUser(7)), None))

    assert chat.banned == []
    assert captured_challenge == []
    assert chat.sent and "правила" in chat.sent[0]


def test_leaving_member_is_ignored(store, captured_challenge, monkeypatch):
    monkeypatch.setattr(user_handlers, "extract_status_change", lambda _cm: (True, False))
    chat = FakeChat()
    asyncio.run(user_handlers.greet_chat_members(_update(chat, FakeUser(7)), None))
    assert chat.banned == [] and chat.sent == [] and captured_challenge == []


def test_no_status_change_is_noop(store, captured_challenge, monkeypatch):
    monkeypatch.setattr(user_handlers, "extract_status_change", lambda _cm: None)
    chat = FakeChat()
    asyncio.run(user_handlers.greet_chat_members(_update(chat, FakeUser(7)), None))
    assert chat.banned == [] and chat.sent == []
