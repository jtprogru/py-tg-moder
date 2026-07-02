# -*- coding: utf-8 -*-
"""Management actions from the dashboard: moderation and forced compaction.

Web-initiated moderation goes through the same Bot API as the chat commands
and mirrors the same storage side-effects; every action is audited with the
web admin's Telegram id as the actor and ``meta.source = "web"``. All POSTs
require a CSRF token bound to the admin's session.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from telegram.error import TelegramError

from core import backups, config
from core.audit import AuditEvent, record_event
from core.duration import format_duration, parse_duration
from core.storage import get_storage
from handlers.admin_handlers import MUTE_PERMISSIONS, UNMUTE_PERMISSIONS
from web.auth import check_csrf, make_csrf, require_admin
from web.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter()

ACTIONS = {
    "ban": "🔨 Пользователь забанен",
    "unban": "✅ Пользователь разбанен",
    "kick": "👢 Пользователь кикнут",
    "mute": "🔇 Пользователь замьючен",
    "unmute": "🔊 Пользователь размьючен",
}
_ACTION_EVENTS = {
    "ban": AuditEvent.BAN,
    "unban": AuditEvent.UNBAN,
    "kick": AuditEvent.KICK,
    "mute": AuditEvent.MUTE,
    "unmute": AuditEvent.UNMUTE,
}


def _result(request: Request, notice: str = "", error: str = "", status_code: int = 200) -> Response:
    return templates.TemplateResponse(request, "_action_result.html", {"notice": notice, "error": error}, status_code=status_code)


def _resolve_target(storage, raw: str) -> Optional[int]:
    """Resolve a form target (numeric id or @username) to a user id."""
    token = raw.strip()
    if token.startswith("@"):
        return storage.resolve_username(token)
    return int(token) if token.isdigit() else None


@router.post("/chats/{chat_id}/actions", response_class=HTMLResponse)
async def perform_action(
    request: Request,
    chat_id: int,
    action: str = Form(...),
    target: str = Form(...),
    duration: str = Form(""),
    reason: str = Form(""),
    csrf: str = Form(""),
    admin: int = Depends(require_admin),
) -> Response:
    if not check_csrf(csrf, admin):
        return _result(request, error="Сессия устарела — обнови страницу и повтори.", status_code=403)
    if action not in ACTIONS:
        return _result(request, error="Неизвестное действие.", status_code=400)

    application = request.app.state.application
    if application is None:
        return _result(request, error="Бот недоступен из веб-процесса.", status_code=503)
    bot = application.bot

    storage = get_storage()
    user_id = await asyncio.to_thread(_resolve_target, storage, target)
    if user_id is None:
        return _result(request, error="Не нашёл пользователя: укажи числовой id или @username того, кто уже писал в чат.", status_code=404)

    seconds = parse_duration(duration.strip()) if duration.strip() else None
    until_ts = int(time.time()) + seconds if seconds else None
    reason = reason.strip() or None

    # The same guardrails as the chat commands: never act on the bot itself,
    # the chat owner or another admin.
    try:
        if user_id == bot.id:
            return _result(request, error="Меня самого модерировать не нужно 🙂", status_code=400)
        admins = await bot.get_chat_administrators(chat_id)
        if user_id in {member.user.id for member in admins}:
            return _result(request, error="Нельзя применять модерацию к администратору или владельцу чата.", status_code=400)

        if action == "ban":
            await bot.ban_chat_member(chat_id, user_id, until_date=until_ts)
        elif action == "unban":
            # only_if_banned: an unban of a present member must not kick them.
            await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
        elif action == "kick":
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        elif action == "mute":
            await bot.restrict_chat_member(chat_id, user_id, permissions=MUTE_PERMISSIONS, until_date=until_ts)
            await asyncio.to_thread(storage.add_mute, chat_id, user_id, until_ts)
        elif action == "unmute":
            await bot.restrict_chat_member(chat_id, user_id, permissions=UNMUTE_PERMISSIONS)
            await asyncio.to_thread(storage.remove_mute, chat_id, user_id)
    except TelegramError as exc:
        logger.warning("[WARN] Web moderation action %s failed: %s", action, exc)
        return _result(request, error=f"Telegram отклонил действие: {exc}", status_code=502)

    meta = {"source": "web"}
    if until_ts is not None:
        meta["until"] = until_ts
    await record_event(chat_id, _ACTION_EVENTS[action], user_id=user_id, actor_id=admin, reason=reason, meta=meta)
    logger.info("[INFO] Web action %s on %s in %s by admin %s", action, user_id, chat_id, admin)

    suffix = f" на {format_duration(seconds)}" if seconds and action in ("ban", "mute") else ""
    return _result(request, notice=f"{ACTIONS[action]}{suffix}.")


# -- forced compaction -----------------------------------------------------------


def _db_size_mb() -> Optional[float]:
    path = get_storage().path
    try:
        return round(os.path.getsize(path) / (1024 * 1024), 2)
    except OSError:
        return None


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, admin: int = Depends(require_admin)) -> Response:
    snapshots = [
        {
            "name": entry["name"],
            "size_mb": round(entry["size"] / (1024 * 1024), 2),
            "when": datetime.fromtimestamp(entry["mtime"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        for entry in await asyncio.to_thread(backups.list_local_backups)
    ]
    context = {
        "retention_days": config.RETENTION_DAYS,
        "purge_hour": config.RETENTION_PURGE_HOUR,
        "db_size_mb": _db_size_mb(),
        "backup_enabled": config.BACKUP_ENABLED,
        "backup_hour": config.BACKUP_HOUR,
        "backup_dir": config.BACKUP_DIR,
        "backup_keep": config.BACKUP_KEEP,
        "s3_configured": backups.s3_configured(),
        "backups": snapshots,
        "csrf": make_csrf(admin),
    }
    return templates.TemplateResponse(request, "admin.html", context)


@router.post("/admin/backup", response_class=HTMLResponse)
async def backup_now(request: Request, csrf: str = Form(""), admin: int = Depends(require_admin)) -> Response:
    if not check_csrf(csrf, admin):
        return _result(request, error="Сессия устарела — обнови страницу и повтори.", status_code=403)
    try:
        meta = await backups.backup_once(actor_id=admin)
    except Exception:
        logger.exception("[ERROR] Manual backup by admin %s failed", admin)
        return _result(request, error="Бэкап не удался — подробности в логах бота.", status_code=500)
    size_mb = round(meta["size"] / (1024 * 1024), 2)
    if meta.get("s3_key"):
        suffix = " и выгружен в S3"
    elif meta.get("s3_error"):
        suffix = ", но выгрузка в S3 не удалась (см. логи)"
    else:
        suffix = ""
    return _result(request, notice=f"Бэкап {meta['file']} ({size_mb} МБ) создан{suffix}.")


@router.post("/admin/compaction/preview", response_class=HTMLResponse)
async def compaction_preview(
    request: Request,
    days_to_keep: int = Form(..., ge=0),
    csrf: str = Form(""),
    admin: int = Depends(require_admin),
) -> Response:
    if not check_csrf(csrf, admin):
        return _result(request, error="Сессия устарела — обнови страницу и повтори.", status_code=403)
    counts = await asyncio.to_thread(get_storage().purge_counts, days_to_keep)
    context = {
        "days_to_keep": days_to_keep,
        "counts": counts,
        "total": sum(counts.values()),
        "csrf": csrf,
    }
    return templates.TemplateResponse(request, "_compaction_preview.html", context)


@router.post("/admin/compaction", response_class=HTMLResponse)
async def compaction_execute(
    request: Request,
    days_to_keep: int = Form(..., ge=0),
    csrf: str = Form(""),
    admin: int = Depends(require_admin),
) -> Response:
    if not check_csrf(csrf, admin):
        return _result(request, error="Сессия устарела — обнови страницу и повтори.", status_code=403)
    storage = get_storage()
    counts = await asyncio.to_thread(storage.purge_old_data, days_to_keep)
    await asyncio.to_thread(storage.vacuum)
    await record_event(0, AuditEvent.COMPACTION_FORCED, actor_id=admin, meta={"source": "web", "days_to_keep": days_to_keep, **counts})
    logger.info("[INFO] Forced compaction by admin %s (keep %s days): %s", admin, days_to_keep, counts)
    removed = sum(counts.values())
    size = _db_size_mb()
    suffix = f" Размер БД теперь {size} МБ." if size is not None else ""
    return _result(request, notice=f"Готово: удалено {removed} строк (история старше {days_to_keep} дн), база сжата.{suffix}")
