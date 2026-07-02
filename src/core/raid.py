# -*- coding: utf-8 -*-
"""Anti-raid mode: temporary hardening when joins spike.

More than ``join_limit`` joins within ``window_seconds`` switches a chat into
raid mode for ``duration_seconds`` (extended while the spike continues). While
active, the captcha gets a halved timeout and a ban fail-action, and newcomer
violations escalate from delete to mute. Join timestamps live in memory only —
a raid is a real-time signal and does not need to survive a restart — but the
start/end of every raid is written to the audit log.
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Optional

from telegram.error import TelegramError

from core import config
from core.audit import AuditEvent, record_event
from core.config import logger

# Strong refs to raid-end watcher tasks (same pattern as captcha timers).
_tasks: set = set()


class RaidTracker:
    """Sliding-window join counter per chat with a temporary "raid" state."""

    def __init__(self, limit: int, window: int, duration: int):
        self.limit = limit
        self.window = window
        self.duration = duration
        self._joins: dict = defaultdict(deque)
        self._active_until: dict = {}
        self._joins_during: dict = {}

    def register_join(self, chat_id: int, now: Optional[float] = None) -> bool:
        """Count a join; return True when this join *starts* raid mode.

        While a raid is active every further join above the threshold silently
        pushes the deadline out, so the mode ends only after the chat has been
        calm for the full duration.
        """
        ts = time.time() if now is None else now
        events = self._joins[chat_id]
        events.append(ts)
        threshold = ts - self.window
        while events and events[0] <= threshold:
            events.popleft()
        over_limit = len(events) > self.limit

        if self.is_active(chat_id, ts):
            self._joins_during[chat_id] = self._joins_during.get(chat_id, 0) + 1
            if over_limit:
                self._active_until[chat_id] = ts + self.duration
            return False

        if over_limit:
            self._active_until[chat_id] = ts + self.duration
            self._joins_during[chat_id] = len(events)
            return True
        return False

    def is_active(self, chat_id: int, now: Optional[float] = None) -> bool:
        ts = time.time() if now is None else now
        return self._active_until.get(chat_id, 0) > ts

    def active_until(self, chat_id: int) -> float:
        return self._active_until.get(chat_id, 0)

    def end(self, chat_id: int) -> int:
        """Clear the raid state; return how many joins happened during it."""
        self._active_until.pop(chat_id, None)
        return self._joins_during.pop(chat_id, 0)


_tracker = RaidTracker(config.RAID_JOIN_LIMIT, config.RAID_WINDOW, config.RAID_DURATION)


def is_raid_active(chat_id: int) -> bool:
    return config.RAID_ENABLED and _tracker.is_active(chat_id)


async def note_join(chat) -> None:
    """Register a join; on a spike, enter raid mode, audit and warn the chat."""
    if not config.RAID_ENABLED:
        return
    if not _tracker.register_join(chat.id):
        return

    await record_event(
        chat.id,
        AuditEvent.RAID_STARTED,
        meta={"join_limit": _tracker.limit, "window": _tracker.window, "duration": _tracker.duration},
    )
    logger.warning("[WARN] Raid mode ON in chat %s (>%s joins in %ss)", chat.id, _tracker.limit, _tracker.window)
    try:
        await chat.send_message("🛡 Обнаружен наплыв новых участников — временно включён усиленный режим проверки.")
    except TelegramError as exc:
        logger.debug("[DEBUG] Could not announce raid mode: %s", exc)

    task = asyncio.create_task(_watch_end(chat.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _watch_end(chat_id: int) -> None:
    """Sleep until the (possibly extended) deadline passes, then log raid end."""
    while True:
        remaining = _tracker.active_until(chat_id) - time.time()
        if remaining <= 0:
            break
        await asyncio.sleep(remaining)
    joins = _tracker.end(chat_id)
    await record_event(chat_id, AuditEvent.RAID_ENDED, meta={"joins": joins})
    logger.info("[INFO] Raid mode OFF in chat %s (%s joins during raid)", chat_id, joins)
