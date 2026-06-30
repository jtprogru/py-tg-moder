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
    def __init__(self, reply_to=None):
        self.reply_to_message = reply_to
        self.from_user = None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeChat:
    def __init__(self, admins):
        self._admins = admins
        self.banned = []
        self.restricted = []

    async def get_administrators(self):
        return self._admins

    async def ban_member(self, user_id):
        self.banned.append(user_id)

    async def restrict_member(self, user_id, permissions):
        self.restricted.append(user_id)


class FakeBot:
    def __init__(self, bot_id):
        self.id = bot_id


class FakeContext:
    def __init__(self, bot_id):
        self.bot = FakeBot(bot_id)


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


def _run(coro):
    return asyncio.run(coro)


def _make(issuer_id, target_user, admins, bot_id=999):
    replied = FakeMessage()
    replied.from_user = target_user
    message = FakeMessage(reply_to=replied)
    chat = FakeChat(admins)
    update = FakeUpdate(message, chat, FakeUser(issuer_id))
    return update, message, chat, FakeContext(bot_id)


def test_ban_refuses_admin_target():
    admin_user = FakeUser(7)
    issuer = 5
    admins = [FakeAdmin(FakeUser(issuer)), FakeAdmin(admin_user)]
    update, message, chat, ctx = _make(issuer, admin_user, admins)
    _run(admin.ban_user(update, ctx))
    assert chat.banned == []
    assert any("администратор" in r.lower() for r in message.replies)


def test_ban_refuses_bot_itself():
    bot_user = FakeUser(999, is_bot=True)
    issuer = 5
    admins = [FakeAdmin(FakeUser(issuer))]
    update, message, chat, ctx = _make(issuer, bot_user, admins, bot_id=999)
    _run(admin.ban_user(update, ctx))
    assert chat.banned == []
    assert message.replies


def test_ban_allows_regular_user():
    target = FakeUser(42)
    issuer = 5
    admins = [FakeAdmin(FakeUser(issuer))]
    update, message, chat, ctx = _make(issuer, target, admins)
    _run(admin.ban_user(update, ctx))
    assert chat.banned == [42]
