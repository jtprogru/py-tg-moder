import asyncio

import pytest

import handlers.media_moderation as media
from core import config


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id

    def mention_html(self):
        return f"user:{self.id}"


class FakeAdmin:
    def __init__(self, user):
        self.user = user


class FakeMessage:
    def __init__(self, voice=None, video=None, video_note=None, location=None):
        self.voice = voice
        self.video = video
        self.video_note = video_note
        self.location = location
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeChat:
    def __init__(self, admins=()):
        self._admins = list(admins)
        self.sent = []

    async def get_administrators(self):
        return self._admins

    async def send_message(self, text, **kwargs):
        notice = FakeMessage()
        self.sent.append(text)
        return notice


class FakeUpdate:
    def __init__(self, message, chat, user):
        self.effective_message = message
        self.effective_chat = chat
        self.effective_user = user


@pytest.fixture(autouse=True)
def no_ttl(monkeypatch):
    # Avoid scheduling background self-delete tasks under asyncio.run.
    monkeypatch.setattr(config, "MEDIA_NOTIFY_TTL", 0)
    monkeypatch.setattr(config, "MEDIA_NOTIFY", True)


# -- build_media_filter ----------------------------------------------------


def test_filter_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "MEDIA_ENABLED", False)
    assert media.build_media_filter() is None


def test_filter_none_when_no_types(monkeypatch):
    monkeypatch.setattr(config, "MEDIA_ENABLED", True)
    for flag in ("MEDIA_BLOCK_VOICE", "MEDIA_BLOCK_VIDEO", "MEDIA_BLOCK_VIDEO_NOTE", "MEDIA_BLOCK_LOCATION"):
        monkeypatch.setattr(config, flag, False)
    assert media.build_media_filter() is None


def test_filter_built_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "MEDIA_ENABLED", True)
    monkeypatch.setattr(config, "MEDIA_BLOCK_VOICE", True)
    assert media.build_media_filter() is not None


# -- moderate_media --------------------------------------------------------


def test_voice_from_user_is_deleted_and_notified():
    msg = FakeMessage(voice=object())
    chat = FakeChat()
    asyncio.run(media.moderate_media(FakeUpdate(msg, chat, FakeUser(42)), None))
    assert msg.deleted is True
    assert chat.sent and "голосовые" in chat.sent[0]


def test_admin_media_is_kept():
    msg = FakeMessage(voice=object())
    chat = FakeChat(admins=[FakeAdmin(FakeUser(42))])
    asyncio.run(media.moderate_media(FakeUpdate(msg, chat, FakeUser(42)), None))
    assert msg.deleted is False
    assert chat.sent == []


def test_no_notice_when_notify_disabled(monkeypatch):
    monkeypatch.setattr(config, "MEDIA_NOTIFY", False)
    msg = FakeMessage(video=object())
    chat = FakeChat()
    asyncio.run(media.moderate_media(FakeUpdate(msg, chat, FakeUser(42)), None))
    assert msg.deleted is True
    assert chat.sent == []


def test_labels_for_each_type():
    assert media._media_label(FakeMessage(voice=object())) == "голосовые сообщения"
    assert media._media_label(FakeMessage(video_note=object())) == "видео-кружки"
    assert media._media_label(FakeMessage(video=object())) == "видео"
    assert media._media_label(FakeMessage(location=object())) == "геолокации"


def test_delete_after_removes_notice():
    notice = FakeMessage()
    asyncio.run(media._delete_after(notice, 0))
    assert notice.deleted is True
