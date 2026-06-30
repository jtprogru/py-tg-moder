import pytest

from core.storage import Storage


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
