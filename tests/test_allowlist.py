import asyncio

import pytest
from telegram.constants import ChatType
from telegram.error import BadRequest

import core.allowlist as allowlist


class FakeChatInfo:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeBot:
    def __init__(self, mapping):
        self._mapping = mapping

    async def get_chat(self, username):
        if username not in self._mapping:
            raise BadRequest("chat not found")
        return FakeChatInfo(self._mapping[username])


class FakeApplication:
    def __init__(self, bot):
        self.bot = bot


class FakeChat:
    def __init__(self, chat_id, chat_type=ChatType.SUPERGROUP):
        self.id = chat_id
        self.type = chat_type
        self.left = False

    async def leave(self):
        self.left = True


class FakeUpdate:
    def __init__(self, chat):
        self.effective_chat = chat


@pytest.fixture(autouse=True)
def _clear_ids():
    allowlist.allowed_chat_ids.clear()
    yield
    allowlist.allowed_chat_ids.clear()


def test_resolve_numeric_and_username(monkeypatch):
    monkeypatch.setattr(allowlist, "ALLOWED_CHATS", [-100123, "12345", "@known", "@missing"])
    app = FakeApplication(FakeBot({"@known": 777}))
    asyncio.run(allowlist.resolve_allowlist(app))
    assert allowlist.allowed_chat_ids == {-100123, 12345, 777}


def test_guard_allows_private_chat():
    calls = []

    @allowlist.restricted_to_allowed_chats
    async def handler(update, context):
        calls.append(update.effective_chat.id)

    update = FakeUpdate(FakeChat(1, ChatType.PRIVATE))
    asyncio.run(handler(update, None))
    assert calls == [1]


def test_guard_allows_allowed_chat():
    allowlist.allowed_chat_ids.add(555)
    calls = []

    @allowlist.restricted_to_allowed_chats
    async def handler(update, context):
        calls.append(update.effective_chat.id)

    update = FakeUpdate(FakeChat(555))
    asyncio.run(handler(update, None))
    assert calls == [555]


def test_guard_leaves_foreign_chat():
    calls = []

    @allowlist.restricted_to_allowed_chats
    async def handler(update, context):
        calls.append(update.effective_chat.id)

    chat = FakeChat(999)
    update = FakeUpdate(chat)
    asyncio.run(handler(update, None))
    assert calls == []
    assert chat.left is True
