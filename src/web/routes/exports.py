# -*- coding: utf-8 -*-
"""Data exports: per-chat statistics as CSV, plus config and DB backup downloads.

CSV files start with a UTF-8 BOM so Excel opens Cyrillic content correctly.
The DB backup is a transactional ``VACUUM INTO`` snapshot — safe to take while
the bot keeps writing. All endpoints are read-only GETs behind admin auth.
"""

import asyncio
import csv
import io
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from core import config
from core.storage import get_storage
from web.auth import require_admin
from web.routes.dashboard import EVENT_LABELS

router = APIRouter(dependencies=[Depends(require_admin)])

_BOM = chr(0xFEFF)  # UTF-8 BOM so Excel detects the encoding


def _iso(ts: Optional[int]) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def _csv_response(filename: str, header: list[str], rows: list[list]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        content=_BOM + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


@router.get("/chats/{chat_id}/export/audit.csv")
async def export_audit(chat_id: int, event: Optional[str] = Query(None), user_id: Optional[int] = Query(None)) -> Response:
    """The full audit journal of a chat (with the current browser filters)."""
    storage = get_storage()
    event = event if event in EVENT_LABELS else None
    rows = await asyncio.to_thread(storage.export_audit, chat_id, event, user_id)
    ids = {r["user_id"] for r in rows if r["user_id"]} | {r["actor_id"] for r in rows if r["actor_id"]}
    names = await asyncio.to_thread(storage.usernames_map, list(ids))
    return _csv_response(
        f"audit-{chat_id}-{_stamp()}.csv",
        ["id", "when_utc", "event", "event_label", "user_id", "username", "actor_id", "actor_username", "reason", "meta", "unix_ts"],
        [
            [
                r["id"],
                _iso(r["created_at"]),
                r["event"],
                EVENT_LABELS.get(r["event"], r["event"]),
                r["user_id"] or "",
                names.get(r["user_id"], ""),
                r["actor_id"] or "",
                names.get(r["actor_id"], ""),
                r["reason"] or "",
                r["meta"] or "",
                r["created_at"],
            ]
            for r in rows
        ],
    )


@router.get("/chats/{chat_id}/export/messages.csv")
async def export_messages(chat_id: int) -> Response:
    """Per-day, per-user message counts for the whole retained history."""
    rows = await asyncio.to_thread(get_storage().export_message_stats, chat_id)
    return _csv_response(
        f"messages-{chat_id}-{_stamp()}.csv",
        ["day", "user_id", "username", "count"],
        [[r["day"], r["user_id"], r["username"] or "", r["count"]] for r in rows],
    )


@router.get("/chats/{chat_id}/export/members.csv")
async def export_members(chat_id: int) -> Response:
    """Every known member with activity numbers and active warn count."""
    rows = await asyncio.to_thread(get_storage().export_members, chat_id)
    return _csv_response(
        f"members-{chat_id}-{_stamp()}.csv",
        ["user_id", "username", "first_seen_utc", "last_seen_utc", "message_count", "active_warns"],
        [[r["user_id"], r["username"] or "", _iso(r["first_seen"]), _iso(r["last_seen"]), r["message_count"], r["active_warns"]] for r in rows],
    )


# -- config & backup (for restarts / redeploys) -----------------------------------


@router.get("/admin/export/config.yaml")
async def export_config() -> FileResponse:
    """The live config.yaml — the single file that defines the bot's behaviour.

    Secrets are never in this file (they live in env vars), so it is safe to
    download and keep next to the deployment.
    """
    return FileResponse(
        config._DEFAULT_CONFIG,
        media_type="application/yaml",
        filename=f"config-{_stamp()}.yaml",
    )


@router.get("/admin/export/env.json")
async def export_env() -> Response:
    """Effective runtime settings that come from env vars, as a checklist.

    Secret *values* are intentionally replaced with set/not-set flags — the
    point is to know what must be provided again after a redeploy.
    """
    payload = {
        "TELEGRAM_BOT_TOKEN": "set" if config.TELEGRAM_BOT_TOKEN else "NOT SET",
        "WEB_SESSION_SECRET": "set" if config.WEB_SESSION_SECRET else "NOT SET",
        "SENTRY_DSN": "set" if config.SENTRY_DSN else "not set",
        "DB_PATH": config.DB_PATH,
        "DEBUG": config.DEBUG,
        "WEB_ENABLED": config.WEB_ENABLED,
        "WEB_HOST": config.WEB_HOST,
        "WEB_PORT": config.WEB_PORT,
        "WEB_PUBLIC_URL": config.WEB_PUBLIC_URL,
        "RETENTION_DAYS": config.RETENTION_DAYS,
        "RETENTION_PURGE_HOUR": config.RETENTION_PURGE_HOUR,
        "BACKUP_ENABLED": config.BACKUP_ENABLED,
        "BACKUP_HOUR": config.BACKUP_HOUR,
        "BACKUP_DIR": config.BACKUP_DIR,
        "BACKUP_KEEP": config.BACKUP_KEEP,
        "S3_ENDPOINT": config.S3_ENDPOINT,
        "S3_REGION": config.S3_REGION,
        "S3_BUCKET": config.S3_BUCKET,
        "S3_PREFIX": config.S3_PREFIX,
        "S3_ACCESS_KEY": "set" if config.S3_ACCESS_KEY else "not set",
        "S3_SECRET_KEY": "set" if config.S3_SECRET_KEY else "not set",
        "admin_ids": sorted(config.ADMIN_IDS),
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="env-{_stamp()}.json"'},
    )


@router.get("/admin/export/backup.sqlite")
async def export_backup() -> FileResponse:
    """A consistent snapshot of the whole database (state + history)."""
    tmp_dir = tempfile.mkdtemp(prefix="moder-backup-")
    dest = os.path.join(tmp_dir, "backup.sqlite")
    await asyncio.to_thread(get_storage().backup_to, dest)
    return FileResponse(
        dest,
        media_type="application/vnd.sqlite3",
        filename=f"moder-backup-{_stamp()}.sqlite",
        background=BackgroundTask(shutil.rmtree, tmp_dir, ignore_errors=True),
    )
