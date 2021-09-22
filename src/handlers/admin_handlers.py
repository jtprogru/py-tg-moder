from telegram import ChatPermissions, Update
from telegram.ext import CallbackContext

from core.config import logger
from handlers.helpers import extract_status_change


def ban_user(update: Update, context: CallbackContext) -> None:
    """Ban user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        update.effective_chat.ban_member(user_id=update.chat_member.new_chat_member.user.id)
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was banned")


def unban_user(update: Update, context: CallbackContext) -> None:
    """Unban user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        update.effective_chat.unban_member(user_id=update.chat_member.new_chat_member.user.id)
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was unbanned")


def mute_user(update: Update, context: CallbackContext) -> None:
    """Mute user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        update.effective_chat.restrict_member(
            user_id=update.chat_member.new_chat_member.user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
            ),
        )
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was muted")


def unmute_user(update: Update, context: CallbackContext) -> None:
    """Unmute user"""

    result = extract_status_change(update.chat_member)

    if result is None:
        return

    admins_list = update.effective_chat.get_administrators()

    if update.message.from_user in admins_list:
        update.effective_chat.restrict_member(
            user_id=update.chat_member.new_chat_member.user.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True,
            ),
        )
        logger.info(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was unmuted")
