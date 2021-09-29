import logging
from telegram import ParseMode, Update
from telegram.ext import CallbackContext

from core.cas import casapi
from core.config import CHAT_RULES_URL

from .helpers import extract_status_change

logger = logging.getLogger(__name__)


def greet_chat_members(update: Update, context: CallbackContext) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        check = casapi.check(user_id=update.chat_member.new_chat_member.user.id)
        logger.debug(f"[DEBUG] User with ID {update.chat_member.new_chat_member.user.id} was checked")
        if check["ok"]:
            update.effective_chat.send_message(
                f'Хомячок {member_name} пришёл.\n\nВелкам и прочти <a href="{CHAT_RULES_URL}">правила</a>!',
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            logger.debug(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was banned")
            update.effective_chat.ban_member(user_id=update.chat_member.new_chat_member.user.id)
    elif was_member and not is_member:
        logger.debug(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was leave")
