import asyncio

import pytest

import handlers.user_cache as uc
from core.storage import Storage


class FakeUser:
    def __init__(self, user_id, username=None, is_bot=False):
        self.id = user_id
        self.username = username
        self.is_bot = is_bot


class FakeChat:
    def __init__(self, chat_id=100, chat_type="supergroup"):
        self.id = chat_id
        self.type = chat_type


class FakeUpdate:
    def __init__(self, user, chat=None, edited=False):
        self.effective_user = user
        self.effective_chat = chat if chat is not None else FakeChat()
        self.edited_message = object() if edited else None


def _stat_rows(store):
    return store._conn.execute("SELECT chat_id, user_id, count FROM message_stats").fetchall()


@pytest.fixture
def store(monkeypatch):
    s = Storage(":memory:")
    monkeypatch.setattr(uc, "get_storage", lambda: s)
    yield s
    s.close()


def test_caches_username(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "alice")), None))
    assert store.resolve_username("alice") == 42


def test_ignores_user_without_username(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, None)), None))
    assert store.resolve_username("alice") is None


def test_ignores_bots(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "botname", is_bot=True)), None))
    assert store.resolve_username("botname") is None
    assert _stat_rows(store) == []


def test_counts_message_stats(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "alice")), None))
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "alice")), None))
    rows = _stat_rows(store)
    assert [(r["chat_id"], r["user_id"], r["count"]) for r in rows] == [(100, 42, 2)]


def test_counts_stats_even_without_username(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, None)), None))
    assert len(_stat_rows(store)) == 1


def test_edits_are_not_counted(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "alice"), edited=True), None))
    assert _stat_rows(store) == []
    assert store.resolve_username("alice") == 42  # username still cached


def test_private_chats_are_not_counted(store):
    asyncio.run(uc.cache_seen_user(FakeUpdate(FakeUser(42, "alice"), chat=FakeChat(chat_type="private")), None))
    assert _stat_rows(store) == []
    assert store.resolve_username("alice") == 42
