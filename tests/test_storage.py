import sqlite3

import pytest

from core.storage import _SCHEMA, Storage


@pytest.fixture
def store():
    s = Storage(":memory:")
    yield s
    s.close()


# -- members ---------------------------------------------------------------


def test_record_member_is_idempotent(store):
    store.record_member(1, 42, now=100)
    store.record_member(1, 42, now=200)  # must not overwrite first_seen
    member = store.get_member(1, 42)
    assert member["first_seen"] == 100
    assert member["message_count"] == 0


def test_touch_member_counts_messages(store):
    assert store.touch_member(1, 42, now=100) == 1
    assert store.touch_member(1, 42, now=110) == 2
    member = store.get_member(1, 42)
    assert member["message_count"] == 2
    assert member["last_seen"] == 110
    assert member["first_seen"] == 100


def test_is_new_member_unknown_user(store):
    assert store.is_new_member(1, 999) is True


def test_is_new_member_graduates_by_message_count(store):
    for ts in range(5):
        store.touch_member(1, 42, now=100 + ts)
    assert store.is_new_member(1, 42, max_messages=5, now=101) is False


def test_is_new_member_graduates_by_age(store):
    store.touch_member(1, 42, now=100)
    assert store.is_new_member(1, 42, max_messages=5, max_age_seconds=10, now=105) is True
    assert store.is_new_member(1, 42, max_messages=5, max_age_seconds=10, now=200) is False


# -- warns -----------------------------------------------------------------


def test_warns_add_count_list(store):
    store.add_warn(1, 42, moderator_id=7, reason="spam", now=100)
    store.add_warn(1, 42, moderator_id=7, reason="flood", now=200)
    assert store.count_warns(1, 42) == 2
    reasons = [w["reason"] for w in store.list_warns(1, 42)]
    assert reasons == ["spam", "flood"]


def test_remove_last_warn(store):
    store.add_warn(1, 42, reason="a", now=100)
    store.add_warn(1, 42, reason="b", now=200)
    assert store.remove_last_warn(1, 42) is True
    assert [w["reason"] for w in store.list_warns(1, 42)] == ["a"]
    assert store.remove_last_warn(1, 99) is False


def test_clear_warns(store):
    store.add_warn(1, 42, now=100)
    store.add_warn(1, 42, now=200)
    assert store.clear_warns(1, 42) == 2
    assert store.count_warns(1, 42) == 0


# -- warns: soft-delete ------------------------------------------------------


def test_clear_warns_keeps_history(store):
    store.add_warn(1, 42, reason="a", now=100)
    store.add_warn(1, 42, reason="b", now=200)
    store.clear_warns(1, 42, now=300)
    assert store.list_warns(1, 42) == []
    history = store.list_warns(1, 42, include_deleted=True)
    assert [w["reason"] for w in history] == ["a", "b"]
    assert all(w["deleted_at"] == 300 for w in history)


def test_remove_last_warn_keeps_history(store):
    store.add_warn(1, 42, reason="a", now=100)
    store.add_warn(1, 42, reason="b", now=200)
    assert store.remove_last_warn(1, 42, now=300) is True
    assert [w["reason"] for w in store.list_warns(1, 42)] == ["a"]
    assert len(store.list_warns(1, 42, include_deleted=True)) == 2


def test_remove_last_warn_skips_soft_deleted(store):
    store.add_warn(1, 42, reason="a", now=100)
    store.remove_last_warn(1, 42, now=200)
    # The only warn left is already soft-deleted — nothing to remove.
    assert store.remove_last_warn(1, 42, now=300) is False


def test_warn_cycle_restarts_after_clear(store):
    store.add_warn(1, 42, now=100)
    store.add_warn(1, 42, now=200)
    store.clear_warns(1, 42, now=300)
    store.add_warn(1, 42, now=400)
    assert store.count_warns(1, 42) == 1  # the next cycle starts clean


# -- message stats -----------------------------------------------------------


def test_record_message_stat_buckets_by_utc_day(store):
    day1, day2 = 1_700_000_000, 1_700_000_000 + 86400  # consecutive UTC days
    store.record_message_stat(1, 42, now=day1)
    store.record_message_stat(1, 42, now=day1 + 60)
    store.record_message_stat(1, 42, now=day2)
    store.record_message_stat(1, 43, now=day2)
    rows = store._conn.execute("SELECT day, user_id, count FROM message_stats ORDER BY day, user_id").fetchall()
    assert [(r["day"], r["user_id"], r["count"]) for r in rows] == [
        ("2023-11-14", 42, 2),
        ("2023-11-15", 42, 1),
        ("2023-11-15", 43, 1),
    ]


# -- migrations ----------------------------------------------------------------


def test_migration_upgrades_v0_database(tmp_path):
    # Build a database exactly as the pre-migration bot would have left it.
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.execute("INSERT INTO warns (chat_id, user_id, moderator_id, reason, created_at) VALUES (1, 42, 7, 'spam', 100)")
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()

    s = Storage(db)
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 1
    columns = {row[1] for row in s._conn.execute("PRAGMA table_info(warns)")}
    assert "deleted_at" in columns
    # Pre-existing warns survive the migration and count as active.
    assert s.count_warns(1, 42) == 1
    s.add_audit_event(1, "ban", user_id=42, now=200)  # new tables are usable
    s.record_message_stat(1, 42, now=200)
    s.close()


def test_fresh_database_is_fully_migrated(store):
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_migration_is_idempotent_across_reconnect(tmp_path):
    db = str(tmp_path / "m.db")
    a = Storage(db)
    a.add_audit_event(1, "warn", user_id=42, now=100)
    a.close()
    b = Storage(db)  # reopening must not re-run migrations
    assert len(b.list_audit_events(chat_id=1)) == 1
    b.close()


# -- mutes -----------------------------------------------------------------


def test_mute_active_and_expired(store):
    store.add_mute(1, 42, until=500, now=100)
    assert store.is_muted(1, 42, now=300) is True
    assert store.is_muted(1, 42, now=600) is False


def test_indefinite_mute(store):
    store.add_mute(1, 42, until=None, now=100)
    assert store.is_muted(1, 42, now=10**9) is True


def test_remove_mute(store):
    store.add_mute(1, 42, until=500, now=100)
    assert store.remove_mute(1, 42) is True
    assert store.is_muted(1, 42, now=300) is False
    assert store.remove_mute(1, 42) is False


def test_get_active_mutes_filters_expired(store):
    store.add_mute(1, 1, until=500, now=100)
    store.add_mute(1, 2, until=None, now=100)
    store.add_mute(1, 3, until=200, now=100)
    active = {m["user_id"] for m in store.get_active_mutes(now=300)}
    assert active == {1, 2}


# -- counters --------------------------------------------------------------


def test_counters(store):
    assert store.get_counter(1, "bans") == 0
    assert store.increment_counter(1, "bans") == 1
    assert store.increment_counter(1, "bans", amount=2) == 3
    assert store.get_counter(1, "bans") == 3


# -- persistence across reconnect (the actual restart criterion) -----------


def test_state_survives_reconnect(tmp_path):
    db = str(tmp_path / "moder.db")

    first = Storage(db)
    first.add_warn(1, 42, reason="spam", now=100)
    first.add_mute(1, 42, until=None, now=100)
    first.increment_counter(1, "bans", amount=4)
    first.touch_member(1, 42, now=100)
    first.close()

    # Reopen as if the bot restarted.
    second = Storage(db)
    assert second.count_warns(1, 42) == 1
    assert second.is_muted(1, 42, now=10**9) is True
    assert second.get_counter(1, "bans") == 4
    assert second.get_member(1, 42)["message_count"] == 1
    second.close()


# -- username -> id cache --------------------------------------------------


def test_remember_and_resolve_username(store):
    store.remember_user(42, "Alice")
    assert store.resolve_username("alice") == 42
    assert store.resolve_username("@Alice") == 42  # @ and case-insensitive


def test_remember_user_updates_id(store):
    store.remember_user(1, "bob")
    store.remember_user(2, "bob")  # username reassigned to a new account
    assert store.resolve_username("bob") == 2


def test_remember_user_without_username_is_noop(store):
    store.remember_user(7, None)
    store.remember_user(7, "")
    assert store.resolve_username("nobody") is None


def test_username_cache_survives_reconnect(tmp_path):
    db = str(tmp_path / "u.db")
    a = Storage(db)
    a.remember_user(99, "carol")
    a.close()
    b = Storage(db)
    assert b.resolve_username("carol") == 99
    b.close()


# -- captchas --------------------------------------------------------------


def test_add_and_list_captcha(store):
    store.add_captcha(1, 42, message_id=555, deadline=1000)
    rows = store.list_captchas()
    assert rows == [{"chat_id": 1, "user_id": 42, "message_id": 555, "deadline": 1000}]


def test_add_captcha_upserts(store):
    store.add_captcha(1, 42, message_id=555, deadline=1000)
    store.add_captcha(1, 42, message_id=777, deadline=2000)  # re-challenge same user
    rows = store.list_captchas()
    assert rows == [{"chat_id": 1, "user_id": 42, "message_id": 777, "deadline": 2000}]


def test_remove_captcha(store):
    store.add_captcha(1, 42, message_id=555, deadline=1000)
    assert store.remove_captcha(1, 42) is True
    assert store.remove_captcha(1, 42) is False  # already gone
    assert store.list_captchas() == []


def test_captcha_survives_reconnect(tmp_path):
    db = str(tmp_path / "c.db")
    a = Storage(db)
    a.add_captcha(1, 42, message_id=555, deadline=1000)
    a.close()
    b = Storage(db)
    assert b.list_captchas() == [{"chat_id": 1, "user_id": 42, "message_id": 555, "deadline": 1000}]
    b.close()
