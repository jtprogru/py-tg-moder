# -*- coding: utf-8 -*-
"""Authentication for the web dashboard.

Login is the Telegram Login Widget: Telegram redirects back with the user's
profile fields plus an HMAC (``hash``) computed with a key derived from the bot
token, so the payload cannot be forged without the token. Only users listed in
``admin_ids`` (config.yaml) are let in; a successful login sets a signed,
timestamped session cookie (itsdangerous).
"""

import hashlib
import hmac
import time
from typing import Optional

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from core import config

SESSION_COOKIE = "tgmoder_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # re-login once a week
AUTH_TTL = 86400  # reject widget payloads older than a day

# Fields the Login Widget may send; anything else in the query string is not
# part of the signed payload and must not enter the data-check string.
_WIDGET_FIELDS = {"id", "first_name", "last_name", "username", "photo_url", "auth_date", "hash"}


def verify_telegram_auth(data: dict[str, str], bot_token: str, now: Optional[int] = None) -> Optional[int]:
    """Validate a Login Widget payload; return the Telegram user id or None.

    Implements https://core.telegram.org/widgets/login#checking-authorization:
    ``hash`` must equal HMAC-SHA256 over the sorted ``key=value`` lines of all
    other fields, keyed with SHA256(bot_token). Stale payloads are rejected so
    a leaked callback URL can't be replayed forever.
    """
    fields = {k: v for k, v in data.items() if k in _WIDGET_FIELDS}
    received_hash = fields.pop("hash", None)
    auth_date = fields.get("auth_date", "")
    user_id = fields.get("id", "")
    if not received_hash or not auth_date.isdigit() or not user_id.isdigit():
        return None

    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hashlib.sha256(bot_token.encode()).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None

    ts = int(time.time()) if now is None else now
    if ts - int(auth_date) > AUTH_TTL:
        return None
    return int(user_id)


def _signer() -> TimestampSigner:
    if not config.WEB_SESSION_SECRET:
        # create_app refuses to start without a secret; this is a safety net.
        raise RuntimeError("WEB_SESSION_SECRET is not set")
    return TimestampSigner(config.WEB_SESSION_SECRET)


def make_session(user_id: int) -> str:
    """Serialize a logged-in admin into a signed cookie value."""
    return _signer().sign(str(user_id)).decode()


def read_session(cookie: Optional[str]) -> Optional[int]:
    """Return the admin's user id from a session cookie, or None if invalid."""
    if not cookie:
        return None
    try:
        raw = _signer().unsign(cookie, max_age=SESSION_MAX_AGE)
    except BadSignature, SignatureExpired:
        return None
    return int(raw) if raw.decode().isdigit() else None


async def require_admin(request: Request) -> int:
    """FastAPI dependency: the current admin's user id, or a redirect to /login."""
    user_id = read_session(request.cookies.get(SESSION_COOKIE))
    if user_id is None or user_id not in config.ADMIN_IDS:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user_id


# -- CSRF ----------------------------------------------------------------------
# State-changing POSTs carry a token bound to the admin's id, signed with the
# same secret but a distinct salt so a session cookie can never pass as one.

CSRF_MAX_AGE = 12 * 3600


def make_csrf(user_id: int) -> str:
    return TimestampSigner(config.WEB_SESSION_SECRET, salt="csrf").sign(str(user_id)).decode()


def check_csrf(token: Optional[str], user_id: int) -> bool:
    if not token:
        return False
    try:
        raw = TimestampSigner(config.WEB_SESSION_SECRET, salt="csrf").unsign(token, max_age=CSRF_MAX_AGE)
    except BadSignature, SignatureExpired:
        return False
    return raw.decode() == str(user_id)
