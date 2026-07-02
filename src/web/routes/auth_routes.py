# -*- coding: utf-8 -*-
"""Login/logout routes: Telegram Login Widget callback and the session cookie."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from core import config
from web.auth import SESSION_COOKIE, SESSION_MAX_AGE, make_session, verify_telegram_auth
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()


def _bot_username(request: Request) -> str:
    application = request.app.state.application
    try:
        return application.bot.username or ""
    except Exception:  # bot not initialized (tests, web-only runs)
        return ""


def _login_page(request: Request, error: str = "", status_code: int = 200) -> Response:
    context = {
        "bot_username": _bot_username(request),
        "public_url": config.WEB_PUBLIC_URL,
        "debug": config.DEBUG,
        "error": error,
    }
    return templates.TemplateResponse(request, "login.html", context, status_code=status_code)


def _login_response(user_id: int) -> Response:
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        make_session(user_id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=not config.DEBUG,  # local dev runs over plain http
        samesite="lax",
    )
    return response


@router.get("/login", response_class=HTMLResponse)
async def login(request: Request) -> Response:
    return _login_page(request)


@router.get("/auth/telegram")
async def auth_telegram(request: Request) -> Response:
    """Callback the Login Widget redirects to with the signed profile payload."""
    user_id = verify_telegram_auth(dict(request.query_params), config.TELEGRAM_BOT_TOKEN or "")
    if user_id is None:
        logger.warning("[WARN] Rejected web login: invalid or stale widget payload")
        return _login_page(request, error="Не удалось проверить подпись Telegram. Попробуй ещё раз.", status_code=403)
    if user_id not in config.ADMIN_IDS:
        logger.warning("[WARN] Rejected web login for %s: not in admin_ids", user_id)
        return _login_page(request, error="Этот Telegram-аккаунт не в списке администраторов панели.", status_code=403)
    logger.info("[INFO] Web login: admin %s", user_id)
    return _login_response(user_id)


@router.get("/auth/dev")
async def auth_dev(request: Request, user_id: int) -> Response:
    """DEBUG-only login bypass: the Login Widget needs a public HTTPS domain,
    which a local dev machine doesn't have."""
    if not config.DEBUG:
        return Response(status_code=404)
    if user_id not in config.ADMIN_IDS:
        return _login_page(request, error="user_id не в списке admin_ids.", status_code=403)
    return _login_response(user_id)


@router.get("/logout")
async def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
