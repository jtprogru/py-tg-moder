from telegram import ChatMember

from handlers.helpers import extract_status_change


class FakeChatMemberUpdated:
    """Minimal stand-in exposing only the `difference()` used by extract_status_change."""

    def __init__(self, diff):
        self._diff = diff

    def difference(self):
        return self._diff


def test_no_status_change_returns_none():
    assert extract_status_change(FakeChatMemberUpdated({})) is None


def test_member_joining_returns_was_false_is_true():
    diff = {"status": (ChatMember.LEFT, ChatMember.MEMBER)}
    assert extract_status_change(FakeChatMemberUpdated(diff)) == (False, True)


def test_member_leaving_returns_was_true_is_false():
    diff = {"status": (ChatMember.MEMBER, ChatMember.LEFT)}
    assert extract_status_change(FakeChatMemberUpdated(diff)) == (True, False)


def test_owner_counts_as_member():
    diff = {"status": (ChatMember.LEFT, ChatMember.OWNER)}
    was_member, is_member = extract_status_change(FakeChatMemberUpdated(diff))
    assert was_member is False
    assert is_member is True
