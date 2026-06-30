"""Cache @username -> id for every user we see.

The Bot API cannot resolve a @username to an id on demand, so the bot
remembers the mapping for everyone who writes in the chat. This is what makes
``/ban @user`` possible without a message to reply to.
"""

import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from core.storage import get_storage


async def cache_seen_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record the author's @username -> id mapping (no-op without a username)."""
    user = update.effective_user
    if user is None or user.is_bot or not user.username:
        return
    await asyncio.to_thread(get_storage().remember_user, user.id, user.username)
