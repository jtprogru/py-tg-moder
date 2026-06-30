import asyncio

import pytest

import handlers.user_cache as uc
from core.storage import Storage


class FakeUser:
    def __init__(self, user_id, username=None, is_bot=False):
        self.id = user_id
        self.username = username
        self.is_bot = is_bot


class FakeUpdate:
    def __init__(self, user):
        self.effective_user = user


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
