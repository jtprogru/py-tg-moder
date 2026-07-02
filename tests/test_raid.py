import asyncio

import pytest

import handlers.captcha as captcha
import handlers.message_moderation as mm
from core import config, raid
from core.raid import RaidTracker

CHAT = 100


class FakeMessage:
    message_id = 555

    def __init__(self):
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeChat:
    def __init__(self, chat_id=CHAT):
        self.id = chat_id
        self.sent = []
        self.banned = []
        self.unbanned = []
        self.restricted = []
        self.deleted_messages = []

    async def send_message(self, text, **kwargs):
        self.sent.append(text)
        return FakeMessage()

    async def ban_member(self, user_id, until_date=None):
        self.banned.append(user_id)

    async def unban_member(self, user_id):
        self.unbanned.append(user_id)

    async def restrict_member(self, user_id, permissions, until_date=None):
        self.restricted.append(user_id)

    async def delete_message(self, message_id):
        self.deleted_messages.append(message_id)


# -- tracker ---------------------------------------------------------------------


def test_tracker_triggers_above_limit():
    tracker = RaidTracker(limit=3, window=60, duration=600)
    assert [tracker.register_join(1, now=100 + i) for i in range(3)] == [False, False, False]
    assert tracker.register_join(1, now=104) is True  # 4th join within the window
    assert tracker.is_active(1, now=105) is True
    assert tracker.is_active(1, now=104 + 601) is False


def test_tracker_window_expires_old_joins():
    tracker = RaidTracker(limit=3, window=60, duration=600)
    for i in range(3):
        tracker.register_join(1, now=100 + i)
    # The 4th join comes after the window slid past the first three.
    assert tracker.register_join(1, now=200) is False
    assert tracker.is_active(1, now=201) is False


def test_tracker_extends_while_spike_continues():
    tracker = RaidTracker(limit=2, window=60, duration=100)
    for i in range(3):
        tracker.register_join(1, now=100 + i)
    assert tracker.is_active(1, now=102) is True
    # Another over-limit join at t=150 pushes the deadline to 250.
    assert tracker.register_join(1, now=150) is False  # silently extends
    assert tracker.is_active(1, now=220) is True
    assert tracker.is_active(1, now=251) is False


def test_tracker_counts_chats_independently():
    tracker = RaidTracker(limit=1, window=60, duration=600)
    tracker.register_join(1, now=100)
    tracker.register_join(1, now=101)
    assert tracker.is_active(1, now=102) is True
    assert tracker.is_active(2, now=102) is False


def test_tracker_end_reports_joins_and_clears():
    tracker = RaidTracker(limit=1, window=60, duration=600)
    for i in range(4):
        tracker.register_join(1, now=100 + i)
    assert tracker.end(1) == 4  # 2 that triggered + 2 during
    assert tracker.is_active(1, now=105) is False


# -- note_join: audit, announcement, end watcher ------------------------------------


def test_note_join_starts_raid_once_and_audits(monkeypatch, audit_store):
    monkeypatch.setattr(raid, "_tracker", RaidTracker(limit=2, window=60, duration=600))
    chat = FakeChat()

    async def scenario():
        for _ in range(5):
            await raid.note_join(chat)

    asyncio.run(scenario())
    events = audit_store.list_audit_events(chat_id=CHAT, event="raid_started")
    assert len(events) == 1  # started once, not on every join over the limit
    assert events[0]["meta"]["join_limit"] == 2
    assert raid.is_raid_active(CHAT) is True
    assert any("усиленный режим" in text for text in chat.sent)


def test_note_join_disabled_by_config(monkeypatch, audit_store):
    monkeypatch.setattr(config, "RAID_ENABLED", False)
    monkeypatch.setattr(raid, "_tracker", RaidTracker(limit=1, window=60, duration=600))
    chat = FakeChat()

    async def scenario():
        for _ in range(5):
            await raid.note_join(chat)

    asyncio.run(scenario())
    assert audit_store.list_audit_events(event="raid_started") == []
    assert raid.is_raid_active(CHAT) is False


def test_raid_end_is_audited(monkeypatch, audit_store):
    monkeypatch.setattr(raid, "_tracker", RaidTracker(limit=1, window=60, duration=0.05))
    chat = FakeChat()

    async def scenario():
        for _ in range(3):
            await raid.note_join(chat)
        assert raid.is_raid_active(CHAT) is True
        await asyncio.sleep(0.15)  # let the watcher fire

    asyncio.run(scenario())
    assert raid.is_raid_active(CHAT) is False
    events = audit_store.list_audit_events(chat_id=CHAT, event="raid_ended")
    assert len(events) == 1
    assert events[0]["meta"]["joins"] == 3


# -- hardening: captcha ----------------------------------------------------------


@pytest.fixture
def captcha_store(monkeypatch, audit_store):
    monkeypatch.setattr(captcha, "get_storage", lambda: audit_store)
    return audit_store


def test_captcha_timeout_halved_during_raid(monkeypatch, captcha_store):
    monkeypatch.setattr(config, "CAPTCHA_TIMEOUT", 60)
    monkeypatch.setattr(raid, "is_raid_active", lambda chat_id: True)
    chat = FakeChat()

    class User:
        id = 42

        def mention_html(self):
            return "user:42"

    asyncio.run(captcha.start_challenge(chat, User()))
    assert any("30 сек" in text for text in chat.sent)
    shown = captcha_store.list_audit_events(event="captcha_shown")[0]
    assert shown["meta"]["timeout"] == 30
    captcha._pending.clear()


def test_captcha_fail_becomes_ban_during_raid(monkeypatch, captcha_store):
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "kick")
    monkeypatch.setattr(raid, "is_raid_active", lambda chat_id: True)
    chat = FakeChat()
    captcha._pending[(CHAT, 42)] = 555

    asyncio.run(captcha._punish_if_pending(chat, 42))
    assert chat.banned == [42]
    assert chat.unbanned == []  # kick would unban; raid forces a real ban
    failed = captcha_store.list_audit_events(event="captcha_failed")[0]
    assert failed["meta"]["action"] == "ban"


def test_captcha_fail_stays_kick_without_raid(monkeypatch, captcha_store):
    monkeypatch.setattr(config, "CAPTCHA_FAIL_ACTION", "kick")
    chat = FakeChat()
    captcha._pending[(CHAT, 42)] = 555

    asyncio.run(captcha._punish_if_pending(chat, 42))
    assert chat.banned == [42]
    assert chat.unbanned == [42]


# -- hardening: newcomer filter ------------------------------------------------------


def test_newcomer_delete_escalates_to_mute_during_raid(monkeypatch, audit_store):
    monkeypatch.setattr(mm, "get_storage", lambda: audit_store)
    monkeypatch.setattr(config, "NEWCOMER_ACTION", "delete")
    monkeypatch.setattr(raid, "is_raid_active", lambda chat_id: True)

    chat = FakeChat()
    message = FakeMessage()
    update = type("U", (), {"effective_chat": chat, "effective_message": message})()

    asyncio.run(mm._enforce(update, None, 42, "ссылка"))
    assert message.deleted is True
    assert chat.restricted == [42]  # escalated from delete to mute
    event = audit_store.list_audit_events(event="newcomer_filtered")[0]
    assert event["meta"] == {"action": "mute", "raid": True}


def test_newcomer_delete_stays_delete_without_raid(monkeypatch, audit_store):
    monkeypatch.setattr(mm, "get_storage", lambda: audit_store)
    monkeypatch.setattr(config, "NEWCOMER_ACTION", "delete")

    chat = FakeChat()
    message = FakeMessage()
    update = type("U", (), {"effective_chat": chat, "effective_message": message})()

    asyncio.run(mm._enforce(update, None, 42, "ссылка"))
    assert chat.restricted == []
    event = audit_store.list_audit_events(event="newcomer_filtered")[0]
    assert event["meta"] == {"action": "delete"}
