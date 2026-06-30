import asyncio

import handlers.admin_handlers as admin


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
    def __init__(self, admins):
        self._admins = admins
        self.banned = []

    async def get_administrators(self):
        return self._admins

    async def ban_member(self, user_id, until_date=None):
        self.banned.append(user_id)


class FakeContext:
    class _Bot:
        id = 999

    bot = _Bot()
    args = []


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


def _make(target_id=42, issuer_id=5):
    spam = FakeMessage(message_id=100)
    spam.from_user = FakeUser(target_id)
    command = FakeMessage(reply_to=spam, message_id=101)
    chat = FakeChat([FakeAdmin(FakeUser(issuer_id))])
    update = FakeUpdate(command, chat, FakeUser(issuer_id))
    return update, spam, chat


def test_ban_deletes_spam_message_when_enabled(monkeypatch):
    monkeypatch.setattr(admin, "DELETE_ON_BAN", True)
    update, spam, chat = _make()
    asyncio.run(admin.ban_user(update, FakeContext()))
    assert chat.banned == [42]
    assert spam.deleted is True


def test_ban_keeps_spam_message_when_disabled(monkeypatch):
    monkeypatch.setattr(admin, "DELETE_ON_BAN", False)
    update, spam, chat = _make()
    asyncio.run(admin.ban_user(update, FakeContext()))
    assert chat.banned == [42]
    assert spam.deleted is False
