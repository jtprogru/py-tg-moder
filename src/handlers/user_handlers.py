import asyncio
import logging

from telegram import LinkPreviewOptions, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import config, raid
from core.audit import AuditEvent, record_event
from core.cas import casapi
from core.config import CHAT_RULES_URL
from core.storage import get_storage

from .captcha import start_challenge
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
        new_user = update.chat_member.new_chat_member.user
        user_id = new_user.id
        storage = get_storage()
        # Record the join so the newcomer age window is measured from here, and
        # cache the joiner's @username so they can be targeted by name later.
        await asyncio.to_thread(storage.record_member, update.effective_chat.id, user_id)
        await asyncio.to_thread(storage.remember_user, user_id, new_user.username)
        await record_event(update.effective_chat.id, AuditEvent.MEMBER_JOINED, user_id=user_id)
        # A join spike flips the chat into raid mode (hardens captcha/filters).
        await raid.note_join(update.effective_chat)
        check = await asyncio.to_thread(casapi.check, user_id=user_id)
        logger.debug(f"[DEBUG] User with ID {user_id} was checked")
        # CAS returns ok=True when the user is listed as a spammer,
        # and ok=False ("Record not found.") when the user is clean.
        if check["ok"]:
            # CAS hit -> ban outright, skipping the captcha.
            logger.info(f"[INFO] User with ID {user_id} found in CAS, was banned")
            await update.effective_chat.ban_member(user_id=user_id)
            await record_event(update.effective_chat.id, AuditEvent.CAS_BAN, user_id=user_id)
        elif config.CAPTCHA_ENABLED:
            # Make the newcomer pass the captcha before they can write or be greeted.
            await start_challenge(update.effective_chat, new_user)
        else:
            await update.effective_chat.send_message(
                f'Хомячок {member_name} пришёл.\n\nВелкам и прочти <a href="{CHAT_RULES_URL}">правила</a>!',
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
    elif was_member and not is_member:
        left_user_id = update.chat_member.new_chat_member.user.id
        await record_event(update.effective_chat.id, AuditEvent.MEMBER_LEFT, user_id=left_user_id)
        logger.debug(f"[INFO] User with ID {left_user_id} was leave")
