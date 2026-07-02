import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes
from telegram.helpers import escape

from core.audit import AuditEvent, record_event
from core.config import WARN_ACTION, WARN_LIMIT, logger
from core.storage import get_storage

from .admin_handlers import MUTE_PERMISSIONS, resolve_target


def _format_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


async def _delete_command(update: Update) -> None:
    """Remove the command message so warns don't pile up in the chat."""
    try:
        await update.effective_message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not delete command message: %s", exc)


async def _auto_punish(update: Update, user_id: int) -> str:
    """Apply the configured punishment when the warn limit is reached.

    Returns a short human-readable description of what happened.
    """
    chat = update.effective_chat
    try:
        if WARN_ACTION == "ban":
            await chat.ban_member(user_id=user_id)
            await record_event(chat.id, AuditEvent.AUTO_BAN, user_id=user_id, meta={"trigger": "warn_limit"})
            logger.info(f"[INFO] User {user_id} auto-banned after reaching warn limit")
            return "забанен"
        await chat.restrict_member(user_id=user_id, permissions=MUTE_PERMISSIONS)
        # Persist the mute so its state survives a restart.
        await asyncio.to_thread(get_storage().add_mute, chat.id, user_id, None)
        await record_event(chat.id, AuditEvent.AUTO_MUTE, user_id=user_id, meta={"trigger": "warn_limit"})
        logger.info(f"[INFO] User {user_id} auto-muted after reaching warn limit")
        return "замьючен"
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Auto-punishment failed for %s: %s", user_id, exc)
        return "не наказан (у меня нет нужных прав)"


async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Warn a user by reply, @username or id; auto-punish at the limit."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    moderator = update.effective_user
    reason = " ".join(resolved.extra_args).strip() if resolved.extra_args else None

    storage = get_storage()
    await asyncio.to_thread(storage.add_warn, chat.id, target.id, moderator.id, reason)
    count = await asyncio.to_thread(storage.count_warns, chat.id, target.id)
    await record_event(chat.id, AuditEvent.WARN, user_id=target.id, actor_id=moderator.id, reason=reason, meta={"count": count})

    text = f"⚠️ {target.mention_html()} предупреждён ({count}/{WARN_LIMIT}).\nПричина: {escape(reason) if reason else '—'}"

    if count >= WARN_LIMIT:
        outcome = await _auto_punish(update, target.id)
        # Reset the counter so the next cycle starts clean (soft-delete keeps history).
        await asyncio.to_thread(storage.clear_warns, chat.id, target.id)
        await record_event(chat.id, AuditEvent.WARNS_CLEARED, user_id=target.id, meta={"trigger": "auto_punish", "count": count})
        text += f"\n\nДостигнут лимит предупреждений — пользователь {outcome}. Счётчик сброшен."

    await update.effective_message.reply_html(text)
    await _delete_command(update)


async def warns_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the warn history of a user by reply, @username or id (admins only)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    warns = await asyncio.to_thread(get_storage().list_warns, chat.id, target.id)

    if not warns:
        await update.effective_message.reply_html(f"У {target.mention_html()} нет предупреждений.")
        return

    lines = [f"Предупреждения {target.mention_html()} — {len(warns)}/{WARN_LIMIT}:"]
    for i, warn in enumerate(warns, start=1):
        reason = escape(warn["reason"]) if warn["reason"] else "—"
        lines.append(f"{i}. {_format_date(warn['created_at'])} — {reason}")
    await update.effective_message.reply_html("\n".join(lines))


async def unwarn_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove the most recent warn from a user by reply, @username or id (admins only)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    storage = get_storage()
    removed = await asyncio.to_thread(storage.remove_last_warn, chat.id, target.id)

    if not removed:
        await update.effective_message.reply_html(f"У {target.mention_html()} нет предупреждений.")
        return

    count = await asyncio.to_thread(storage.count_warns, chat.id, target.id)
    await record_event(chat.id, AuditEvent.UNWARN, user_id=target.id, actor_id=update.effective_user.id, meta={"count": count})
    await update.effective_message.reply_html(f"С {target.mention_html()} снято последнее предупреждение. Осталось: {count}/{WARN_LIMIT}.")
    await _delete_command(update)
