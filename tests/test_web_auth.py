import hashlib
import hmac

import pytest

from core import config
from web import auth as web_auth
from web.auth import make_session, read_session, verify_telegram_auth

TOKEN = "12345:dummy-token"


def _signed_payload(user_id=7, auth_date=1_700_000_000, **extra) -> dict:
    """Build a Login Widget payload signed exactly like Telegram does."""
    fields = {"id": str(user_id), "first_name": "Тест", "auth_date": str(auth_date), **extra}
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hashlib.sha256(TOKEN.encode()).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return fields


def test_valid_payload_returns_user_id():
    payload = _signed_payload(user_id=7, username="alice")
    assert verify_telegram_auth(payload, TOKEN, now=1_700_000_100) == 7


def test_tampered_payload_is_rejected():
    payload = _signed_payload(user_id=7)
    payload["id"] = "999"  # signature no longer covers the data
    assert verify_telegram_auth(payload, TOKEN, now=1_700_000_100) is None


def test_wrong_token_is_rejected():
    payload = _signed_payload(user_id=7)
    assert verify_telegram_auth(payload, "12345:other-token", now=1_700_000_100) is None


def test_stale_auth_date_is_rejected():
    payload = _signed_payload(user_id=7, auth_date=1_700_000_000)
    assert verify_telegram_auth(payload, TOKEN, now=1_700_000_000 + 86401) is None


def test_missing_hash_is_rejected():
    payload = _signed_payload(user_id=7)
    payload.pop("hash")
    assert verify_telegram_auth(payload, TOKEN, now=1_700_000_100) is None


def test_extra_query_params_do_not_break_verification():
    # A callback URL may carry unrelated params; they are not part of the
    # signed payload and must be ignored.
    payload = _signed_payload(user_id=7)
    payload["utm_source"] = "x"
    assert verify_telegram_auth(payload, TOKEN, now=1_700_000_100) == 7


# -- session cookie ------------------------------------------------------------


@pytest.fixture
def session_secret(monkeypatch):
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "test-secret")


def test_session_round_trip(session_secret):
    assert read_session(make_session(42)) == 42


def test_session_bad_signature(session_secret, monkeypatch):
    cookie = make_session(42)
    monkeypatch.setattr(config, "WEB_SESSION_SECRET", "another-secret")
    assert read_session(cookie) is None


def test_session_none_cookie(session_secret):
    assert read_session(None) is None


def test_session_expiry(session_secret, monkeypatch):
    cookie = make_session(42)
    monkeypatch.setattr(web_auth, "SESSION_MAX_AGE", -1)
    assert read_session(cookie) is None
