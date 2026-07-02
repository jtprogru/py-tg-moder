# -*- coding: utf-8 -*-
"""Daily retention purge of aged history.

History tables (audit log, soft-deleted warns, per-day message stats) are
hard-deleted once they are older than the configured retention window. The
purge runs once right after startup (catching up after downtime) and then
daily at a fixed UTC hour — a plain asyncio task, same pattern as the captcha
timers (no job-queue dependency).
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import config
from core.config import logger
from core.storage import get_storage

# Strong ref to the loop task so it is not garbage-collected.
_task: Optional[asyncio.Task] = None


def seconds_until(hour_utc: int, now: Optional[int] = None) -> int:
    """Seconds from ``now`` to the next occurrence of ``hour_utc:00`` UTC."""
    ts = int(time.time()) if now is None else now
    current = datetime.fromtimestamp(ts, tz=timezone.utc)
    target = current.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return int((target - current).total_seconds())


async def _purge_once() -> None:
    counts = await asyncio.to_thread(get_storage().purge_old_data, config.RETENTION_DAYS)
    logger.info("[INFO] Retention purge done (keep %s days): %s", config.RETENTION_DAYS, counts)


async def retention_loop() -> None:
    """Purge on startup, then daily at RETENTION_PURGE_HOUR UTC, forever."""
    while True:
        try:
            await _purge_once()
        except Exception:
            # One failed purge must not kill the loop; the next run retries.
            logger.exception("[ERROR] Retention purge failed")
        await asyncio.sleep(seconds_until(config.RETENTION_PURGE_HOUR))


def start_retention(application) -> None:
    """Start the retention task once the bot is up (called from post_init)."""
    global _task
    _task = asyncio.create_task(retention_loop())
