# -*- coding: utf-8 -*-
"""Audit log of moderation events.

Every moderation action (manual command, automatic punishment, captcha
outcome, filter hit, join/leave) is appended to the ``audit_log`` table so the
history survives for analytics even when the live state changes (e.g. warns
are cleared after an auto-punishment). Events are recorded only after the
Telegram action succeeded — failed actions are not audited.
"""

import asyncio
import enum
import logging
from typing import Optional

from core.storage import get_storage

logger = logging.getLogger(__name__)


class AuditEvent(enum.StrEnum):
    """Event types stored in ``audit_log.event``."""

    BAN = "ban"
    UNBAN = "unban"
    KICK = "kick"
    MUTE = "mute"
    UNMUTE = "unmute"
    WARN = "warn"
    UNWARN = "unwarn"
    WARNS_CLEARED = "warns_cleared"
    AUTO_BAN = "auto_ban"
    AUTO_MUTE = "auto_mute"
    CAPTCHA_SHOWN = "captcha_shown"
    CAPTCHA_PASSED = "captcha_passed"
    CAPTCHA_FAILED = "captcha_failed"
    CAS_BAN = "cas_ban"
    FLOOD_MUTE = "flood_mute"
    NEWCOMER_FILTERED = "newcomer_filtered"
    MEDIA_DELETED = "media_deleted"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    COMPACTION_FORCED = "compaction_forced"
    RAID_STARTED = "raid_started"
    RAID_ENDED = "raid_ended"
    BACKUP_CREATED = "backup_created"


async def record_event(
    chat_id: int,
    event: AuditEvent,
    *,
    user_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    reason: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """Persist an audit event; a storage failure must never break moderation."""
    try:
        await asyncio.to_thread(get_storage().add_audit_event, chat_id, str(event), user_id, actor_id, reason, meta)
    except Exception:
        logger.exception("[ERROR] Failed to record audit event %s in chat %s", event, chat_id)
