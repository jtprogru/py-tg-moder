"""Content moderation for messages from newcomers.

New users (within their first N messages / first day) get their links,
forwards, @-mentions and Telegram invites filtered. Edited messages are
re-checked automatically — python-telegram-bot content filters also match
``edited_message`` — closing the "clean text, then edit into spam" trick.
"""

import asyncio
from typing import Optional

from telegram import Message, MessageEntity, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from core import config
from core.config import logger
from core.storage import get_storage

from .admin_handlers import MUTE_PERMISSIONS
from .warn_handlers import _auto_punish


def _is_telegram_invite(url: str) -> bool:
    low = url.lower()
    return ("t.me/+" in low) or ("t.me/joinchat" in low) or ("telegram.me/joinchat" in low)


def find_violation(message: Message) -> Optional[str]:
    """Return a short reason if the message breaks a newcomer rule, else None."""
    if config.NEWCOMER_BLOCK_FORWARDS and message.forward_origin is not None:
        return "форвард"

    entities = list(message.entities or []) + list(message.caption_entities or [])
    text = message.text or message.caption or ""

    if config.NEWCOMER_BLOCK_LINKS:
        for entity in entities:
            if entity.type in (MessageEntity.URL, MessageEntity.TEXT_LINK):
                url = entity.url or text[entity.offset : entity.offset + entity.length]
                return "telegram-инвайт" if _is_telegram_invite(url) else "ссылка"

    if config.NEWCOMER_BLOCK_MENTIONS:
        for entity in entities:
            if entity.type in (MessageEntity.MENTION, MessageEntity.TEXT_MENTION):
                return "@-упоминание"

    return None


async def _enforce(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, reason: str) -> None:
    """Delete the offending message and apply the configured action."""
    chat = update.effective_chat
    message = update.effective_message
    storage = get_storage()

    try:
        await message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not delete newcomer message: %s", exc)

    await asyncio.to_thread(storage.increment_counter, chat.id, "newcomer_filtered")

    if config.NEWCOMER_ACTION == "mute":
        try:
            await chat.restrict_member(user_id=user_id, permissions=MUTE_PERMISSIONS)
            await asyncio.to_thread(storage.add_mute, chat.id, user_id, None)
        except (BadRequest, Forbidden) as exc:
            logger.warning("[WARN] Could not mute newcomer %s: %s", user_id, exc)
    elif config.NEWCOMER_ACTION == "warn":
        await asyncio.to_thread(storage.add_warn, chat.id, user_id, context.bot.id, f"авто: {reason}")
        count = await asyncio.to_thread(storage.count_warns, chat.id, user_id)
        if count >= config.WARN_LIMIT:
            await _auto_punish(update, user_id)
            await asyncio.to_thread(storage.clear_warns, chat.id, user_id)

    logger.info("[INFO] Newcomer %s message filtered (%s, action=%s)", user_id, reason, config.NEWCOMER_ACTION)


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Filter newcomer messages; re-runs on edits to catch post-hoc spam."""
    if not config.NEWCOMER_FILTER_ENABLED:
        return

    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None or user.is_bot:
        return

    storage = get_storage()
    is_edit = update.edited_message is not None

    # Decide newness from stored state first, then count fresh (not edits) messages.
    is_new = await asyncio.to_thread(
        storage.is_new_member,
        chat.id,
        user.id,
        config.NEWCOMER_MAX_MESSAGES,
        config.NEWCOMER_MAX_AGE,
    )
    if not is_edit:
        await asyncio.to_thread(storage.touch_member, chat.id, user.id)

    if not is_new:
        return

    reason = find_violation(message)
    if reason is None:
        return

    # Acting is rare, so the admin lookup here stays cheap; never touch admins.
    admins = await chat.get_administrators()
    if user.id in {admin.user.id for admin in admins}:
        return

    await _enforce(update, context, user.id, reason)
