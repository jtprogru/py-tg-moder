from datetime import datetime, timezone

import pytest

from core.retention import seconds_until
from core.storage import Storage


@pytest.fixture
def store():
    s = Storage(":memory:")
    yield s
    s.close()


def _ts(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


# -- next-run computation ------------------------------------------------------


def test_seconds_until_later_today():
    assert seconds_until(4, now=_ts(2026, 7, 1, 2, 0)) == 2 * 3600


def test_seconds_until_wraps_to_next_day():
    assert seconds_until(4, now=_ts(2026, 7, 1, 5, 0)) == 23 * 3600


def test_seconds_until_exact_hour_waits_full_day():
    assert seconds_until(4, now=_ts(2026, 7, 1, 4, 0)) == 24 * 3600


# -- purge policy ----------------------------------------------------------------

NOW = _ts(2026, 7, 1, 12, 0)
CUTOFF = _ts(2026, 6, 21)  # retention_days=10 -> start of UTC day 10 days back


def test_purge_audit_log_boundary(store):
    store.add_audit_event(1, "warn", user_id=42, now=CUTOFF - 1)
    store.add_audit_event(1, "warn", user_id=42, now=CUTOFF)
    counts = store.purge_old_data(10, now=NOW)
    assert counts["audit_log"] == 1
    assert [e["created_at"] for e in store.list_audit_events(chat_id=1)] == [CUTOFF]


def test_purge_removes_only_soft_deleted_warns(store):
    # Old but still active warn: live moderation state, must survive.
    store.add_warn(1, 42, reason="активный", now=CUTOFF - 100)
    # Soft-deleted long ago: history past retention, must go.
    store.add_warn(1, 43, reason="старый", now=CUTOFF - 100)
    store.remove_last_warn(1, 43, now=CUTOFF - 50)
    # Soft-deleted recently: history still within retention, must survive.
    store.add_warn(1, 44, reason="свежий", now=CUTOFF - 100)
    store.remove_last_warn(1, 44, now=CUTOFF + 50)

    counts = store.purge_old_data(10, now=NOW)
    assert counts["warns"] == 1
    assert store.count_warns(1, 42) == 1
    assert store.list_warns(1, 43, include_deleted=True) == []
    assert len(store.list_warns(1, 44, include_deleted=True)) == 1


def test_purge_message_stats_by_day(store):
    store.record_message_stat(1, 42, now=CUTOFF - 1)  # 2026-06-20
    store.record_message_stat(1, 42, now=CUTOFF)  # 2026-06-21
    counts = store.purge_old_data(10, now=NOW)
    assert counts["message_stats"] == 1


def test_purge_leaves_state_tables_alone(store):
    store.record_member(1, 42, now=100)
    store.add_mute(1, 42, until=None, now=100)
    store.add_captcha(1, 42, message_id=5, deadline=200)
    store.remember_user(42, "alice")
    store.increment_counter(1, "flood_muted")

    store.purge_old_data(10, now=NOW)

    assert store.get_member(1, 42) is not None
    assert store.is_muted(1, 42, now=NOW) is True
    assert len(store.list_captchas()) == 1
    assert store.resolve_username("alice") == 42
    assert store.get_counter(1, "flood_muted") == 1
