import csv
import io
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core import config
from web.app import create_app
from web.auth import SESSION_COOKIE, make_session

ADMIN_ID = 7
CHAT = 100


class FakeBot:
    id = 999
    username = "moder_bot"

    async def get_chat(self, chat_id):
        return SimpleNamespace(title=f"Чат {chat_id}", username=None)


@pytest.fixture
def client(monkeypatch, audit_store):
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "ADMIN_IDS", frozenset({ADMIN_ID}))
    app = create_app(SimpleNamespace(bot=FakeBot()))
    with TestClient(app) as c:
        c.cookies.set(SESSION_COOKIE, make_session(ADMIN_ID))
        yield c


def _seed(store):
    store.remember_user(42, "alice")
    store.record_member(CHAT, 42, now=1_700_000_000)
    store.record_message_stat(CHAT, 42, now=1_700_000_000)
    store.record_message_stat(CHAT, 42, now=1_700_000_060)
    store.add_audit_event(CHAT, "warn", user_id=42, actor_id=ADMIN_ID, reason="спам, с запятой", now=1_700_000_100)
    store.add_audit_event(CHAT, "ban", user_id=42, actor_id=ADMIN_ID, meta={"until": None}, now=1_700_000_200)
    store.add_warn(CHAT, 42, moderator_id=ADMIN_ID, reason="флуд", now=1_700_000_150)


def _parse_csv(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    text = response.text
    assert text.startswith("﻿")  # UTF-8 BOM for Excel
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def test_audit_csv(client, audit_store):
    _seed(audit_store)
    rows = _parse_csv(client.get(f"/chats/{CHAT}/export/audit.csv"))
    assert rows[0][:6] == ["id", "when_utc", "event", "event_label", "user_id", "username"]
    assert len(rows) == 3  # header + 2 events, oldest first
    warn_row = rows[1]
    assert warn_row[2] == "warn"
    assert warn_row[3] == "предупреждение"
    assert warn_row[5] == "alice"
    assert warn_row[8] == "спам, с запятой"  # csv-модуль сам заботится о запятых


def test_audit_csv_respects_filters(client, audit_store):
    _seed(audit_store)
    rows = _parse_csv(client.get(f"/chats/{CHAT}/export/audit.csv?event=ban"))
    assert len(rows) == 2
    assert rows[1][2] == "ban"


def test_messages_csv(client, audit_store):
    _seed(audit_store)
    rows = _parse_csv(client.get(f"/chats/{CHAT}/export/messages.csv"))
    assert rows[0] == ["day", "user_id", "username", "count"]
    assert rows[1] == ["2023-11-14", "42", "alice", "2"]


def test_members_csv(client, audit_store):
    _seed(audit_store)
    rows = _parse_csv(client.get(f"/chats/{CHAT}/export/members.csv"))
    assert rows[0] == ["user_id", "username", "first_seen_utc", "last_seen_utc", "message_count", "active_warns"]
    assert rows[1][0] == "42"
    assert rows[1][1] == "alice"
    assert rows[1][5] == "1"  # active warn from _seed


def test_config_yaml_download(client):
    response = client.get("/admin/export/config.yaml")
    assert response.status_code == 200
    assert "allowed_chats" in response.text
    assert "attachment" in response.headers["content-disposition"]


def test_env_json_masks_secrets(client, monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "1234:real-token")
    monkeypatch.setattr(config, "S3_SECRET_KEY", "s3-real-secret")
    response = client.get("/admin/export/env.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["TELEGRAM_BOT_TOKEN"] == "set"
    assert payload["WEB_SESSION_SECRET"] == "set"
    assert payload["S3_SECRET_KEY"] == "set"
    assert "real-token" not in response.text
    assert "test-secret" not in response.text
    assert "s3-real-secret" not in response.text
    assert payload["admin_ids"] == [ADMIN_ID]


def test_backup_is_a_working_sqlite_snapshot(client, audit_store, tmp_path):
    _seed(audit_store)
    response = client.get("/admin/export/backup.sqlite")
    assert response.status_code == 200
    assert "moder-backup-" in response.headers["content-disposition"]

    snapshot = tmp_path / "restored.sqlite"
    snapshot.write_bytes(response.content)
    conn = sqlite3.connect(snapshot)
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1  # migrations carried over
    conn.close()


def test_exports_require_login(client):
    client.cookies.delete(SESSION_COOKIE)
    for path in (
        f"/chats/{CHAT}/export/audit.csv",
        f"/chats/{CHAT}/export/messages.csv",
        f"/chats/{CHAT}/export/members.csv",
        "/admin/export/config.yaml",
        "/admin/export/env.json",
        "/admin/export/backup.sqlite",
    ):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
