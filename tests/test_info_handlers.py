import asyncio

import handlers.info_handlers as info


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeAdmin:
    def __init__(self, user):
        self.user = user


class FakeChat:
    def __init__(self, chat_type, admins=()):
        self.type = chat_type
        self._admins = admins

    async def get_administrators(self):
        return self._admins


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


def _run(coro):
    return asyncio.run(coro)


def test_start_mentions_private_bot():
    msg = FakeMessage()
    update = FakeUpdate(msg, FakeChat("private"), FakeUser(1))
    _run(info.start(update, None))
    assert msg.replies and "приватный" in msg.replies[0].lower()


def test_help_for_regular_user_has_no_moderation_block():
    user = FakeUser(7)
    msg = FakeMessage()
    update = FakeUpdate(msg, FakeChat("supergroup", admins=[]), user)
    _run(info.help_command(update, None))
    assert "/ban" not in msg.replies[0]
    assert "/ping" in msg.replies[0]


def test_help_for_admin_includes_moderation_block():
    user = FakeUser(7)
    msg = FakeMessage()
    chat = FakeChat("supergroup", admins=[FakeAdmin(FakeUser(7))])
    update = FakeUpdate(msg, chat, user)
    _run(info.help_command(update, None))
    assert "/ban" in msg.replies[0]
