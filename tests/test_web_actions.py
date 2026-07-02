from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from telegram.error import BadRequest

from core import config
from web.app import create_app
from web.auth import SESSION_COOKIE, make_csrf, make_session

ADMIN_ID = 7  # web admin (not a chat admin)
CHAT_ADMIN_ID = 1  # chat owner per FakeBot
CHAT = 100


class FakeBot:
    id = 999
    username = "moder_bot"

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def get_chat(self, chat_id):
        return SimpleNamespace(title=f"Чат {chat_id}", username=None)

    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=SimpleNamespace(id=CHAT_ADMIN_ID))]

    def _record(self, *call):
        if self.fail:
            raise BadRequest("Not enough rights")
        self.calls.append(call)

    async def ban_chat_member(self, chat_id, user_id, until_date=None):
        self._record("ban", chat_id, user_id, until_date)

    async def unban_chat_member(self, chat_id, user_id, only_if_banned=None):
        self._record("unban", chat_id, user_id, only_if_banned)

    async def restrict_chat_member(self, chat_id, user_id, permissions=None, until_date=None):
        self._record("restrict", chat_id, user_id, permissions, until_date)


@pytest.fixture
def bot():
    return FakeBot()


@pytest.fixture
def client(monkeypatch, audit_store, bot):
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({ADMIN_ID}))
    monkeypatch.setattr(config, "DEBUG", False)
    app = create_app(SimpleNamespace(bot=bot))
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, make_session(ADMIN_ID))
        yield c


def _post_action(client, csrf=None, **overrides):
    form = {"action": "ban", "target": "42", "duration": "", "reason": "", "csrf": csrf if csrf is not None else make_csrf(ADMIN_ID)}
    form.update(overrides)
    return client.post(f"/chats/{CHAT}/actions", data=form)


# -- CSRF ------------------------------------------------------------------------


def test_action_without_csrf_is_rejected(client, bot):
    assert _post_action(client, csrf="").status_code == 403
    assert bot.calls == []


def test_action_with_foreign_csrf_is_rejected(client, bot):
    assert _post_action(client, csrf=make_csrf(999)).status_code == 403
    assert bot.calls == []


# -- moderation actions ------------------------------------------------------------


def test_ban_by_id_calls_bot_and_audits(client, bot, audit_store):
    response = _post_action(client, reason="спам")
    assert response.status_code == 200
    assert "забанен" in response.text
    assert bot.calls == [("ban", CHAT, 42, None)]
    event = audit_store.list_audit_events(chat_id=CHAT, event="ban")[0]
    assert event["user_id"] == 42
    assert event["actor_id"] == ADMIN_ID
    assert event["reason"] == "спам"
    assert event["meta"] == {"source": "web"}


def test_ban_with_duration(client, bot, audit_store):
    response = _post_action(client, duration="1h")
    assert response.status_code == 200
    call = bot.calls[0]
    assert call[0] == "ban" and call[3] is not None  # until_date set
    assert audit_store.list_audit_events(event="ban")[0]["meta"]["until"] == call[3]


def test_ban_by_username(client, bot, audit_store):
    audit_store.remember_user(42, "spammer")
    response = _post_action(client, target="@spammer")
    assert response.status_code == 200
    assert bot.calls == [("ban", CHAT, 42, None)]


def test_mute_mirrors_storage(client, bot, audit_store):
    response = _post_action(client, action="mute", duration="30m")
    assert response.status_code == 200
    assert bot.calls[0][0] == "restrict"
    assert audit_store.is_muted(CHAT, 42) is True
    assert audit_store.list_audit_events(event="mute")[0]["actor_id"] == ADMIN_ID


def test_unmute_removes_mute(client, bot, audit_store):
    audit_store.add_mute(CHAT, 42, until=None)
    response = _post_action(client, action="unmute")
    assert response.status_code == 200
    assert audit_store.is_muted(CHAT, 42) is False


def test_kick_bans_then_unbans(client, bot):
    response = _post_action(client, action="kick")
    assert response.status_code == 200
    assert [c[0] for c in bot.calls] == ["ban", "unban"]


def test_unban_uses_only_if_banned(client, bot):
    response = _post_action(client, action="unban")
    assert response.status_code == 200
    assert bot.calls == [("unban", CHAT, 42, True)]


def test_chat_admin_is_protected(client, bot, audit_store):
    response = _post_action(client, target=str(CHAT_ADMIN_ID))
    assert response.status_code == 400
    assert bot.calls == []
    assert audit_store.list_audit_events(event="ban") == []


def test_bot_itself_is_protected(client, bot):
    assert _post_action(client, target=str(FakeBot.id)).status_code == 400
    assert bot.calls == []


def test_unknown_target_is_404(client, bot):
    assert _post_action(client, target="@nobody").status_code == 404
    assert bot.calls == []


def test_telegram_error_is_reported(monkeypatch, audit_store):
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({ADMIN_ID}))
    bot = FakeBot(fail=True)
    app = create_app(SimpleNamespace(bot=bot))
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, make_session(ADMIN_ID))
        response = _post_action(client)
    assert response.status_code == 502
    assert "Telegram отклонил" in response.text
    assert audit_store.list_audit_events(event="ban") == []  # failed action not audited


def test_actions_require_login(client, bot):
    client.cookies.delete(SESSION_COOKIE)
    response = client.post(f"/chats/{CHAT}/actions", data={"action": "ban", "target": "42", "csrf": ""}, follow_redirects=False)
    assert response.status_code == 303


# -- forced compaction --------------------------------------------------------------


def test_admin_page_renders(client):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Принудительный компактинг" in response.text


def test_compaction_preview_counts_without_deleting(client, audit_store):
    audit_store.add_audit_event(CHAT, "warn", user_id=42, now=100)  # ancient history
    response = client.post("/admin/compaction/preview", data={"days_to_keep": "1", "csrf": make_csrf(ADMIN_ID)})
    assert response.status_code == 200
    assert "Будет безвозвратно удалено 1 строк" in response.text
    assert audit_store.count_audit_events(chat_id=CHAT) == 1  # dry run


def test_compaction_executes_and_audits(client, audit_store):
    audit_store.add_audit_event(CHAT, "warn", user_id=42, now=100)
    audit_store.add_warn(CHAT, 42, now=100)
    audit_store.clear_warns(CHAT, 42, now=200)
    response = client.post("/admin/compaction", data={"days_to_keep": "1", "csrf": make_csrf(ADMIN_ID)})
    assert response.status_code == 200
    assert "Готово" in response.text
    assert audit_store.count_audit_events(chat_id=CHAT) == 0
    assert audit_store.list_warns(CHAT, 42, include_deleted=True) == []
    event = audit_store.list_audit_events(event="compaction_forced")[0]
    assert event["actor_id"] == ADMIN_ID
    assert event["meta"]["days_to_keep"] == 1
    assert event["meta"]["audit_log"] == 1


def test_compaction_requires_csrf(client, audit_store):
    audit_store.add_audit_event(CHAT, "warn", user_id=42, now=100)
    response = client.post("/admin/compaction", data={"days_to_keep": "0", "csrf": ""})
    assert response.status_code == 403
    assert audit_store.count_audit_events(chat_id=CHAT) == 1
