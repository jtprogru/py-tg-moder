import asyncio
import time
from typing import Awaitable, Callable, NamedTuple, Optional

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from core.audit import AuditEvent, record_event
from core.config import DELETE_ON_BAN, logger
from core.duration import format_duration, parse_duration
from core.storage import get_storage

MUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
)

UNMUTE_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
)


class _TargetUser(NamedTuple):
    """A moderation target identified by id (and optional @username).

    Duck-types the bits of ``telegram.User`` the handlers use when the target
    comes from an argument rather than a replied-to message.
    """

    id: int
    username: Optional[str] = None

    def mention_html(self) -> str:
        label = f"@{self.username}" if self.username else str(self.id)
        return f'<a href="tg://user?id={self.id}">{label}</a>'


class ResolvedTarget(NamedTuple):
    user: object  # telegram.User or _TargetUser — both expose .id / .mention_html()
    extra_args: list  # command args left after consuming the target token


def _resolve_token(token: str) -> Optional[_TargetUser]:
    """Resolve a ``@username`` or numeric id argument to a target, or None."""
    if token.startswith("@"):
        username = token[1:]
        if not username:
            return None
        user_id = get_storage().resolve_username(username)
        return _TargetUser(user_id, username.lower()) if user_id is not None else None
    if token.isdigit():
        return _TargetUser(int(token))
    return None


async def resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[ResolvedTarget]:
    """Validate an admin command and resolve the user it targets.

    The issuer must be a chat administrator. The target may come from a replied-to
    message, or from a ``@username`` / numeric id as the first argument. Returns a
    :class:`ResolvedTarget` (with any leftover args), or ``None`` if not applicable
    (issuer not an admin, target unknown, or target protected — an admin/owner or
    the bot itself). Friendly notices are sent for user-facing failures.
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        return None

    admins = await chat.get_administrators()
    admin_ids = {admin.user.id for admin in admins}
    if user.id not in admin_ids:
        return None

    if message.reply_to_message is not None:
        target = message.reply_to_message.from_user
        extra_args = list(context.args or [])
    elif context.args:
        target = await asyncio.to_thread(_resolve_token, context.args[0])
        if target is None:
            await message.reply_text("Не нашёл такого пользователя. Укажи числовой id или @username того, кто уже писал в чат.")
            return None
        extra_args = list(context.args[1:])
    else:
        await message.reply_text("Укажи цель: ответом на сообщение, либо @username или числовым id.")
        return None

    if target is None:
        return None

    # Protect privileged targets: never act on admins/owner or the bot itself,
    # so an accidental command gives a friendly notice instead of a silent
    # Telegram rejection surfacing as a Sentry error.
    if target.id == context.bot.id:
        await message.reply_text("Меня самого модерировать не нужно 🙂")
        return None
    if target.id in admin_ids:
        await message.reply_text("Нельзя применять модерацию к администратору или владельцу чата.")
        return None

    return ResolvedTarget(target, extra_args)


async def _apply_action(
    update: Update,
    action: Callable[[], Awaitable[object]],
    success_text: str,
) -> bool:
    """Run a moderation ``action``, report the result, and clean up.

    On success a short confirmation is posted in the chat and the command
    message is removed so commands don't pile up. If the bot lacks the required
    admin rights, the issuer gets a clear notice instead of a silent Telegram
    rejection surfacing only as a Sentry error. Returns ``True`` on success.
    """
    message = update.effective_message
    try:
        await action()
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Moderation action failed: %s", exc)
        await message.reply_text("Не удалось выполнить команду: у меня нет нужных прав администратора в этом чате.")
        return False

    await message.reply_text(success_text)
    try:
        await message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not delete command message: %s", exc)
    return True


def _duration_from(extra_args: list) -> Optional[int]:
    """Read an optional duration (e.g. ``30m``, ``1h``, ``1d``) from leftover args."""
    return parse_duration(extra_args[0]) if extra_args else None


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban a user by reply, @username or id; optional duration (/ban @user 1d)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    spam = update.effective_message.reply_to_message
    duration = _duration_from(resolved.extra_args)
    until_ts = int(time.time()) + duration if duration else None
    suffix = f" на {format_duration(duration)}" if duration else ""

    if not await _apply_action(update, lambda: chat.ban_member(user_id=target.id, until_date=until_ts), f"🔨 Пользователь забанен{suffix}."):
        return
    await record_event(chat.id, AuditEvent.BAN, user_id=target.id, actor_id=update.effective_user.id, meta={"until": until_ts})
    logger.info(f"[INFO] User with ID {target.id} was banned (until={until_ts})")

    # Remove the offending message the ban was issued in reply to.
    if DELETE_ON_BAN and spam is not None:
        try:
            await spam.delete()
            logger.info(f"[INFO] Spam message {spam.message_id} from {target.id} was deleted")
        except (BadRequest, Forbidden) as exc:
            logger.debug("[DEBUG] Could not delete spam message: %s", exc)


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban a user by reply, @username or id (admins only)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    if not await _apply_action(update, lambda: chat.unban_member(user_id=target.id), "✅ Пользователь разбанен."):
        return
    await record_event(chat.id, AuditEvent.UNBAN, user_id=target.id, actor_id=update.effective_user.id)
    logger.info(f"[INFO] User with ID {target.id} was unbanned")


async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kick a user by reply, @username or id: ban then immediately unban.

    The user is removed from the chat but is free to rejoin later.
    """
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat

    async def _kick() -> None:
        await chat.ban_member(user_id=target.id)
        await chat.unban_member(user_id=target.id)

    if not await _apply_action(update, _kick, "👢 Пользователь кикнут."):
        return
    await record_event(chat.id, AuditEvent.KICK, user_id=target.id, actor_id=update.effective_user.id)
    logger.info(f"[INFO] User with ID {target.id} was kicked")


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute a user by reply, @username or id; optional duration (/mute @user 30m)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    duration = _duration_from(resolved.extra_args)
    until_ts = int(time.time()) + duration if duration else None
    suffix = f" на {format_duration(duration)}" if duration else ""

    if not await _apply_action(
        update, lambda: chat.restrict_member(user_id=target.id, permissions=MUTE_PERMISSIONS, until_date=until_ts), f"🔇 Пользователь замьючен{suffix}."
    ):
        return
    # Native until_date lifts the mute automatically; we also record it so the
    # state is visible and survives a restart.
    await asyncio.to_thread(get_storage().add_mute, chat.id, target.id, until_ts)
    await record_event(chat.id, AuditEvent.MUTE, user_id=target.id, actor_id=update.effective_user.id, meta={"until": until_ts})
    logger.info(f"[INFO] User with ID {target.id} was muted (until={until_ts})")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute a user by reply, @username or id (admins only)."""
    resolved = await resolve_target(update, context)
    if resolved is None:
        return
    target = resolved.user

    chat = update.effective_chat
    if not await _apply_action(update, lambda: chat.restrict_member(user_id=target.id, permissions=UNMUTE_PERMISSIONS), "🔊 Пользователь размьючен."):
        return
    await asyncio.to_thread(get_storage().remove_mute, chat.id, target.id)
    await record_event(chat.id, AuditEvent.UNMUTE, user_id=target.id, actor_id=update.effective_user.id)
    logger.info(f"[INFO] User with ID {target.id} was unmuted")
