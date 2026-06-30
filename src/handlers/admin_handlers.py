from telegram import ChatPermissions, Update
from telegram.ext import ContextTypes

from core.config import logger
from handlers.helpers import extract_status_change


async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = await update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        await update.effective_chat.ban_member(user_id=update.chat_member.new_chat_member.user.id)
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was banned")


async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unban user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = await update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        await update.effective_chat.unban_member(user_id=update.chat_member.new_chat_member.user.id)
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was unbanned")


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mute user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = await update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        await update.effective_chat.restrict_member(
            user_id=update.chat_member.new_chat_member.user.id,
            permissions=ChatPermissions(
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
            ),
        )
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was muted")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Unmute user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = await update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        await update.effective_chat.restrict_member(
            user_id=update.chat_member.new_chat_member.user.id,
            permissions=ChatPermissions(
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
            ),
        )
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was unmuted")
