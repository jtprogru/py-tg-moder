from typing import Optional

from telegram import ChatPermissions, Update, User
from telegram.ext import ContextTypes

from core.config import logger

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
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)


async def _resolve_target(update: Update) -> Optional[User]:
    """Validate an admin command and return the user it targets.

    The command must be sent by a chat administrator as a reply to the target
    user's message. Returns the target ``User`` or ``None`` if the command is
    not applicable (not a reply, or the issuer is not an admin).
    """
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if message is None or chat is None or user is None:
        return None

    if message.reply_to_message is None:
        await message.reply_text("Команду нужно отправить ответом на сообщение пользователя.")
        return None

    admins = await chat.get_administrators()
    if user.id not in {admin.user.id for admin in admins}:
        return None

    return message.reply_to_message.from_user


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban the author of the replied-to message (admins only)."""
    target = await _resolve_target(update)
    if target is None:
        return

    await update.effective_chat.ban_member(user_id=target.id)
    logger.info(f"[INFO] User with ID {target.id} was banned")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban the author of the replied-to message (admins only)."""
    target = await _resolve_target(update)
    if target is None:
        return

    await update.effective_chat.unban_member(user_id=target.id)
    logger.info(f"[INFO] User with ID {target.id} was unbanned")


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute the author of the replied-to message (admins only)."""
    target = await _resolve_target(update)
    if target is None:
        return

    await update.effective_chat.restrict_member(user_id=target.id, permissions=MUTE_PERMISSIONS)
    logger.info(f"[INFO] User with ID {target.id} was muted")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute the author of the replied-to message (admins only)."""
    target = await _resolve_target(update)
    if target is None:
        return

    await update.effective_chat.restrict_member(user_id=target.id, permissions=UNMUTE_PERMISSIONS)
    logger.info(f"[INFO] User with ID {target.id} was unmuted")
