"""Cache @username -> id for every user we see, and count message statistics.

The Bot API cannot resolve a @username to an id on demand, so the bot
remembers the mapping for everyone who writes in the chat. This is what makes
``/ban @user`` possible without a message to reply to.

This group-2 handler sees every non-service message, so it is also where
per-day message statistics are counted (all message types, unlike
``members.message_count`` which only counts what the newcomer filter sees).
"""

import asyncio

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from core.storage import get_storage


async def cache_seen_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record the author's @username -> id mapping and count the message."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None or user.is_bot:
        return

    storage = get_storage()
    # Count fresh group messages only: edits are not new messages, and private
    # DMs are not part of any chat's statistics.
    if update.edited_message is None and chat.type != ChatType.PRIVATE:
        await asyncio.to_thread(storage.record_message_stat, chat.id, user.id)

    if not user.username:
        return
    await asyncio.to_thread(storage.remember_user, user.id, user.username)
