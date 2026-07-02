import asyncio

import pytest

from core import audit
from core.audit import AuditEvent, record_event
from core.storage import Storage


@pytest.fixture
def store():
    s = Storage(":memory:")
    yield s
    s.close()


# -- storage layer -----------------------------------------------------------


def test_add_and_list_events_newest_first(store):
    store.add_audit_event(1, "warn", user_id=42, actor_id=7, reason="спам", now=100)
    store.add_audit_event(1, "ban", user_id=42, actor_id=7, now=200)
    events = store.list_audit_events(chat_id=1)
    assert [e["event"] for e in events] == ["ban", "warn"]
    assert events[1]["reason"] == "спам"


def test_meta_json_round_trip(store):
    store.add_audit_event(1, "mute", user_id=42, meta={"until": 500, "источник": "тест"}, now=100)
    event = store.list_audit_events(chat_id=1)[0]
    assert event["meta"] == {"until": 500, "источник": "тест"}
    store.add_audit_event(1, "kick", user_id=42, now=200)
    assert store.list_audit_events(event="kick")[0]["meta"] is None


def test_list_events_filters(store):
    store.add_audit_event(1, "warn", user_id=42, now=100)
    store.add_audit_event(1, "warn", user_id=43, now=200)
    store.add_audit_event(2, "ban", user_id=42, now=300)

    assert len(store.list_audit_events(chat_id=1)) == 2
    assert len(store.list_audit_events(event="ban")) == 1
    assert len(store.list_audit_events(user_id=42)) == 2
    assert len(store.list_audit_events(since=200)) == 2  # inclusive lower bound
    assert len(store.list_audit_events(until=200)) == 1  # exclusive upper bound
    assert len(store.list_audit_events(chat_id=1, user_id=43, event="warn")) == 1


def test_list_events_pagination(store):
    for i in range(5):
        store.add_audit_event(1, "warn", user_id=42, now=100 + i)
    page = store.list_audit_events(chat_id=1, limit=2, offset=2)
    assert [e["created_at"] for e in page] == [102, 101]


def test_event_accepts_strenum(store):
    store.add_audit_event(1, AuditEvent.CAS_BAN, user_id=42, now=100)
    assert store.list_audit_events(event="cas_ban")[0]["event"] == "cas_ban"


# -- record_event helper -------------------------------------------------------


def test_record_event_persists(audit_store):
    asyncio.run(record_event(1, AuditEvent.WARN, user_id=42, actor_id=7, reason="спам", meta={"count": 1}))
    events = audit_store.list_audit_events(chat_id=1)
    assert len(events) == 1
    assert events[0]["event"] == "warn"
    assert events[0]["actor_id"] == 7
    assert events[0]["meta"] == {"count": 1}


def test_record_event_swallows_storage_errors(monkeypatch):
    def _boom():
        raise RuntimeError("db is gone")

    monkeypatch.setattr(audit, "get_storage", _boom)
    # Must not raise — a broken audit trail must never break moderation.
    asyncio.run(record_event(1, AuditEvent.BAN, user_id=42))
