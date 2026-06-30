import asyncio
import logging
from telegram import LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.cas import casapi
from core.config import CHAT_RULES_URL

from .helpers import extract_status_change

logger = logging.getLogger(__name__)


async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    member_name = update.chat_member.new_chat_member.user.mention_html()

    if not was_member and is_member:
        check = await asyncio.to_thread(casapi.check, user_id=update.chat_member.new_chat_member.user.id)
        logger.debug(f"[DEBUG] User with ID {update.chat_member.new_chat_member.user.id} was checked")
        if check["ok"]:
            await update.effective_chat.send_message(
                f'Хомячок {member_name} пришёл.\n\nВелкам и прочти <a href="{CHAT_RULES_URL}">правила</a>!',
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        else:
            logger.debug(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was banned")
            await update.effective_chat.ban_member(user_id=update.chat_member.new_chat_member.user.id)
    elif was_member and not is_member:
        logger.debug(f"[INFO] User with ID {update.chat_member.new_chat_member.user.id} was leave")
