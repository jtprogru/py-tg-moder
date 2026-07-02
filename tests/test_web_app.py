import pytest
from fastapi.testclient import TestClient

from core import config
from web.app import create_app
from web.auth import SESSION_COOKIE, make_session


class FakeChatInfo:
    def __init__(self, title):
        self.title = title
        self.username = None


class FakeBot:
    username = "moder_bot"

    async def get_chat(self, chat_id):
        return FakeChatInfo(f"Чат {chat_id}")


class FakeApplication:
    bot = FakeBot()


ADMIN_ID = 7


@pytest.fixture
def client(monkeypatch, audit_store):
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({ADMIN_ID}))
    monkeypatch.setattr(config, "DEBUG", False)
    app = create_app(FakeApplication())
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    client.cookies.set(SESSION_COOKIE, make_session(ADMIN_ID))
    return client


def _seed(store, chat_id=100):
    store.record_member(chat_id, 42, now=1_700_000_000)
    store.record_message_stat(chat_id, 42)
    store.remember_user(42, "alice")
    store.add_audit_event(chat_id, "member_joined", user_id=42)
    store.add_audit_event(chat_id, "captcha_shown", user_id=42)
    store.add_audit_event(chat_id, "captcha_passed", user_id=42)
    store.add_audit_event(chat_id, "ban", user_id=42, actor_id=ADMIN_ID, reason="спам", meta={"until": None})
    store.add_warn(chat_id, 42, moderator_id=ADMIN_ID, reason="флуд")


# -- no session ---------------------------------------------------------------


def test_healthz_needs_no_auth(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_pages_redirect_to_login_without_session(client):
    for path in ("/", "/chats/100", "/chats/100/audit"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login"


def test_session_of_non_admin_is_rejected(client):
    client.cookies.set(SESSION_COOKIE, make_session(999))
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303


def test_login_page_renders_widget(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert 'data-telegram-login="moder_bot"' in response.text


def test_dev_login_disabled_outside_debug(client):
    assert client.get("/auth/dev?user_id=7", follow_redirects=False).status_code == 404


def test_auth_telegram_rejects_garbage(client):
    response = client.get("/auth/telegram?id=7&auth_date=1&hash=ff", follow_redirects=False)
    assert response.status_code == 403


# -- authenticated pages ---------------------------------------------------------


def test_overview_redirects_to_single_chat(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/chats/100"


def test_overview_lists_multiple_chats(admin_client, audit_store):
    _seed(audit_store, chat_id=100)
    _seed(audit_store, chat_id=200)
    response = admin_client.get("/")
    assert response.status_code == 200
    assert "Чат 100" in response.text and "Чат 200" in response.text


def test_chat_page_shows_stats_and_charts(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/chats/100")
    assert response.status_code == 200
    assert "@alice" in response.text  # top posters resolve usernames
    assert "капча пройдена" in response.text
    assert "100%" in response.text  # 1 passed / 1 resolved
    assert 'id="chart-data"' in response.text


def test_chat_page_clamps_unknown_period(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/chats/100?days=9999")
    assert response.status_code == 200


def test_chat_page_raid_tile(admin_client, audit_store, monkeypatch):
    from core import raid

    _seed(audit_store)
    response = admin_client.get("/chats/100")
    assert "спокойно" in response.text

    monkeypatch.setattr(raid, "is_raid_active", lambda chat_id: True)
    response = admin_client.get("/chats/100")
    assert "активен" in response.text


def test_audit_page_lists_events_with_reasons(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/chats/100/audit")
    assert response.status_code == 200
    assert "спам" in response.text
    assert "бан" in response.text


def test_audit_filter_by_event(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/chats/100/audit?event=ban")
    assert "Всего записей: 1" in response.text


def test_audit_htmx_request_returns_partial(admin_client, audit_store):
    _seed(audit_store)
    response = admin_client.get("/chats/100/audit", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<html" not in response.text  # partial, not the full page


def test_logout_clears_session(admin_client):
    response = admin_client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


# -- storage aggregates behind the dashboard -------------------------------------


def test_dashboard_aggregates(audit_store):
    _seed(audit_store, chat_id=100)
    assert audit_store.list_chats() == [100]
    assert audit_store.member_totals(100)["members"] == 1
    assert audit_store.audit_totals(100, 0)["ban"] == 1
    assert audit_store.top_posters(100, "1970-01-01") == [{"user_id": 42, "count": 1}]
    assert audit_store.top_warned(100, 0) == [{"user_id": 42, "count": 1}]
    assert audit_store.usernames_map([42]) == {42: "alice"}
    assert audit_store.count_audit_events(chat_id=100) == 4
    series = audit_store.audit_series(100, 0)
    assert {row["event"] for row in series} == {"member_joined", "captcha_shown", "captcha_passed", "ban"}
