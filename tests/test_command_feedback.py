import asyncio

from telegram.error import Forbidden

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
    def __init__(self, admins, fail=False):
        self._admins = admins
        self._fail = fail
        self.banned = []

    async def get_administrators(self):
        return self._admins

    async def ban_member(self, user_id):
        if self._fail:
            raise Forbidden("not enough rights")
        self.banned.append(user_id)


class FakeContext:
    class _Bot:
        id = 999

    bot = _Bot()


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


def _make(fail=False, target_id=42, issuer_id=5):
    spam = FakeMessage(message_id=100)
    spam.from_user = FakeUser(target_id)
    command = FakeMessage(reply_to=spam, message_id=101)
    chat = FakeChat([FakeAdmin(FakeUser(issuer_id))], fail=fail)
    update = FakeUpdate(command, chat, FakeUser(issuer_id))
    return update, command, chat


def test_successful_ban_confirms_and_deletes_command():
    update, command, chat = _make()
    asyncio.run(admin.ban_user(update, FakeContext()))
    assert chat.banned == [42]
    assert command.replies  # confirmation posted
    assert command.deleted is True  # command message cleaned up


def test_missing_rights_reports_to_admin_and_keeps_command():
    update, command, chat = _make(fail=True)
    asyncio.run(admin.ban_user(update, FakeContext()))
    assert chat.banned == []
    assert any("прав" in r.lower() for r in command.replies)
    assert command.deleted is False
