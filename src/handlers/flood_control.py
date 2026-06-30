"""Flood control: temporarily mute users who send too many messages too fast.

The per-user message timestamps live in memory only — flood is a real-time
signal and does not need to survive a restart. The mute itself uses Telegram's
native ``until_date`` so it lifts automatically without any timer of our own;
it is also recorded in storage for visibility.
"""

import asyncio
import time
from collections import defaultdict, deque

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from core import config
from core.config import logger
from core.storage import get_storage

from .admin_handlers import MUTE_PERMISSIONS


class FloodTracker:
    """Sliding-window message counter per (chat, user)."""

    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self._events: dict = defaultdict(deque)

    def record(self, key, now: float) -> bool:
        """Record a message; return True if the user is now over the limit."""
        events = self._events[key]
        events.append(now)
        threshold = now - self.window
        while events and events[0] <= threshold:
            events.popleft()
        return len(events) > self.limit

    def reset(self, key) -> None:
        self._events.pop(key, None)


_tracker = FloodTracker(config.FLOOD_LIMIT, config.FLOOD_WINDOW)


async def flood_control(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a user who exceeds the message rate within the configured window."""
    if not config.FLOOD_ENABLED:
        return

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None or user.is_bot:
        return

    key = (chat.id, user.id)
    if not _tracker.record(key, time.monotonic()):
        return

    # Over the limit — but never mute an admin (checked only now, so rarely).
    admins = await chat.get_administrators()
    if user.id in {admin.user.id for admin in admins}:
        _tracker.reset(key)
        return

    until_ts = int(time.time()) + config.FLOOD_MUTE_SECONDS
    try:
        await chat.restrict_member(user_id=user.id, permissions=MUTE_PERMISSIONS, until_date=until_ts)
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Could not mute flooding user %s: %s", user.id, exc)
        _tracker.reset(key)
        return

    storage = get_storage()
    await asyncio.to_thread(storage.add_mute, chat.id, user.id, until_ts)
    await asyncio.to_thread(storage.increment_counter, chat.id, "flood_muted")
    _tracker.reset(key)

    logger.info("[INFO] User %s muted for %ss for flooding", user.id, config.FLOOD_MUTE_SECONDS)
    await message.reply_html(f"⏳ {user.mention_html()} замьючен на {config.FLOOD_MUTE_SECONDS} сек за флуд.")
