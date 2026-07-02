# -*- coding: utf-8 -*-
"""Scheduled database backups.

Once a day at BACKUP_HOUR UTC a consistent ``VACUUM INTO`` snapshot lands in
BACKUP_DIR; only the newest BACKUP_KEEP files are kept. With S3 configured the
snapshot is additionally uploaded to the bucket and the same keep-N rotation
is applied to the prefix. A run missed during downtime is caught up on
startup — but a fresh snapshot from the last day suppresses that, so a
crash-looping bot does not rotate good backups away with near-identical ones.
Same plain-asyncio pattern as core.retention.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Optional

from core import config
from core.audit import AuditEvent, record_event
from core.config import logger
from core.retention import seconds_until
from core.s3 import S3Client
from core.storage import get_storage

# Strong ref to the loop task so it is not garbage-collected.
_task: Optional[asyncio.Task] = None

_PREFIX = "moder-"
_SUFFIX = ".sqlite"


def _is_backup(name: str) -> bool:
    return name.startswith(_PREFIX) and name.endswith(_SUFFIX)


def list_local_backups() -> list[dict]:
    """Existing local snapshots, newest first (also feeds the admin page)."""
    try:
        names = os.listdir(config.BACKUP_DIR)
    except OSError:
        return []
    entries = []
    # The timestamp in the name makes lexicographic order chronological.
    for name in sorted(names, reverse=True):
        if not _is_backup(name):
            continue
        try:
            stat = os.stat(os.path.join(config.BACKUP_DIR, name))
        except OSError:
            continue
        entries.append({"name": name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
    return entries


def s3_configured() -> bool:
    return bool(config.S3_ENDPOINT and config.S3_BUCKET and config.S3_ACCESS_KEY and config.S3_SECRET_KEY)


def _make_snapshot(now: Optional[int] = None) -> str:
    """``VACUUM INTO`` a new snapshot file and return its path. Runs in a thread."""
    ts = int(time.time()) if now is None else now
    stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    path = os.path.join(config.BACKUP_DIR, f"{_PREFIX}{stamp}{_SUFFIX}")
    if os.path.exists(path):
        # Two runs within the same second (manual button); VACUUM INTO
        # refuses to overwrite, and the replaced snapshot is equivalent.
        os.remove(path)
    get_storage().backup_to(path)
    return path


def _rotate_local() -> list[str]:
    """Drop local snapshots beyond BACKUP_KEEP; returns removed names."""
    removed = []
    for entry in list_local_backups()[config.BACKUP_KEEP :]:
        try:
            os.remove(os.path.join(config.BACKUP_DIR, entry["name"]))
            removed.append(entry["name"])
        except OSError:
            logger.exception("[ERROR] Failed to remove old backup %s", entry["name"])
    return removed


def _mirror_to_s3(path: str) -> Optional[str]:
    """Upload the snapshot and apply keep-N rotation to the bucket prefix.

    Runs in a thread; returns the uploaded key, or None when S3 is not
    configured. Snapshots are a few MB, reading into memory is fine.
    """
    if not s3_configured():
        return None
    client = S3Client(
        endpoint=config.S3_ENDPOINT,
        region=config.S3_REGION,
        bucket=config.S3_BUCKET,
        access_key=config.S3_ACCESS_KEY,
        secret_key=config.S3_SECRET_KEY,
    )
    key = config.S3_PREFIX + os.path.basename(path)
    with open(path, "rb") as fr:
        client.put_object(key, fr.read())
    ours = sorted((k for k in client.list_keys(config.S3_PREFIX) if _is_backup(k[len(config.S3_PREFIX) :])), reverse=True)
    for old in ours[config.BACKUP_KEEP :]:
        client.delete_object(old)
    return key


async def backup_once(actor_id: Optional[int] = None) -> dict:
    """One full backup run: snapshot, local rotation, optional S3 mirror.

    Used by both the daily loop and the manual button on the admin page
    (which passes the admin as ``actor_id``). Returns the summary that is
    also recorded to the audit log.
    """
    path = await asyncio.to_thread(_make_snapshot)
    size = os.path.getsize(path)
    removed = await asyncio.to_thread(_rotate_local)
    meta = {"file": os.path.basename(path), "size": size, "rotated": len(removed)}
    try:
        key = await asyncio.to_thread(_mirror_to_s3, path)
    except Exception:
        # The local snapshot is intact; a failed upload must not fail the run.
        logger.exception("[ERROR] Backup upload to S3 failed")
        meta["s3_error"] = True
    else:
        if key:
            meta["s3_key"] = key
    await record_event(0, AuditEvent.BACKUP_CREATED, actor_id=actor_id, meta=meta)
    logger.info("[INFO] Backup done: %s", meta)
    return meta


def _due_on_startup(now: Optional[int] = None) -> bool:
    """Catch up a run *missed* during downtime, but no more than that: back up
    on startup only when the newest local snapshot is over a day old (or absent)."""
    backups = list_local_backups()
    if not backups:
        return True
    ts = int(time.time()) if now is None else now
    return ts - max(entry["mtime"] for entry in backups) >= 86400


async def backup_loop() -> None:
    """Catch up a missed run on startup, then back up daily at BACKUP_HOUR UTC."""
    try:
        if await asyncio.to_thread(_due_on_startup):
            await backup_once()
    except Exception:
        logger.exception("[ERROR] Startup backup failed")
    while True:
        await asyncio.sleep(seconds_until(config.BACKUP_HOUR))
        try:
            await backup_once()
        except Exception:
            # One failed backup must not kill the loop; the next run retries.
            logger.exception("[ERROR] Scheduled backup failed")


def start_backups(application) -> None:
    """Start the backup task once the bot is up (called from post_init)."""
    global _task
    if not config.BACKUP_ENABLED:
        return
    _task = asyncio.create_task(backup_loop())
