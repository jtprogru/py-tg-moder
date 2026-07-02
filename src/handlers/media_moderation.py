"""Managed deletion of disallowed media types.

Which media types are removed is driven entirely by config, admins are never
touched, and the author optionally gets a short notice explaining why — the
notice self-deletes after a TTL so it doesn't become noise.
"""

import asyncio
from typing import Optional

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes, filters

from core import config
from core.audit import AuditEvent, record_event
from core.config import logger

# Background tasks for self-deleting notices; kept referenced so they are not
# garbage-collected before they run.
_pending_notices: set = set()


def build_media_filter() -> Optional[filters.BaseFilter]:
    """Build the message filter for the configured media types, or None if off."""
    if not config.MEDIA_ENABLED:
        return None
    parts = []
    if config.MEDIA_BLOCK_VOICE:
        parts.append(filters.VOICE)
    if config.MEDIA_BLOCK_VIDEO:
        parts.append(filters.VIDEO)
    if config.MEDIA_BLOCK_VIDEO_NOTE:
        parts.append(filters.VIDEO_NOTE)
    if config.MEDIA_BLOCK_LOCATION:
        parts.append(filters.LOCATION)
    if not parts:
        return None
    combined = parts[0]
    for part in parts[1:]:
        combined |= part
    return combined


def _media_label(message: Message) -> str:
    if message.voice is not None:
        return "голосовые сообщения"
    if message.video_note is not None:
        return "видео-кружки"
    if message.video is not None:
        return "видео"
    if message.location is not None:
        return "геолокации"
    return "медиа этого типа"


async def _delete_after(message: Message, ttl: int) -> None:
    try:
        await asyncio.sleep(ttl)
        await message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not delete media notice: %s", exc)


async def moderate_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a disallowed-media message from a non-admin and explain why."""
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if message is None or chat is None or user is None:
        return

    # Admins may post any media.
    admins = await chat.get_administrators()
    if user.id in {admin.user.id for admin in admins}:
        return

    label = _media_label(message)
    try:
        await message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not delete media message: %s", exc)
        return
    await record_event(chat.id, AuditEvent.MEDIA_DELETED, user_id=user.id, meta={"type": label})
    logger.info("[INFO] Deleted %s from user %s", label, user.id)

    if not config.MEDIA_NOTIFY:
        return

    try:
        notice = await chat.send_message(
            f"{user.mention_html()}, {label} в этом чате запрещены.",
            parse_mode=ParseMode.HTML,
        )
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not send media notice: %s", exc)
        return

    if config.MEDIA_NOTIFY_TTL > 0:
        task = asyncio.create_task(_delete_after(notice, config.MEDIA_NOTIFY_TTL))
        _pending_notices.add(task)
        task.add_done_callback(_pending_notices.discard)
