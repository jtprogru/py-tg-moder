import logging
from functools import wraps

from telegram.constants import ChatType
from telegram.error import TelegramError

from core.config import ALLOWED_CHATS

logger = logging.getLogger(__name__)

# Numeric chat ids the bot is allowed to operate in. Populated once at startup
# by ``resolve_allowlist`` (see bot.py post_init). Empty until then.
allowed_chat_ids: set[int] = set()


def _looks_numeric(value: str) -> bool:
    return value.lstrip("-").isdigit()


async def resolve_allowlist(application) -> None:
    """Resolve configured chats (ids or @usernames) to numeric ids once on start.

    Numeric entries are used as-is; @username entries are resolved through the
    Bot API. Anything that cannot be resolved is logged and skipped rather than
    crashing the bot.
    """
    bot = application.bot
    for entry in ALLOWED_CHATS:
        if isinstance(entry, int):
            allowed_chat_ids.add(entry)
            continue
        text = str(entry).strip()
        if _looks_numeric(text):
            allowed_chat_ids.add(int(text))
            continue
        try:
            chat = await bot.get_chat(text)
            allowed_chat_ids.add(chat.id)
            logger.info("[INFO] Resolved allowed chat %s -> %s", text, chat.id)
        except TelegramError as exc:
            logger.warning("[WARN] Could not resolve allowed chat %s: %s", text, exc)
    logger.info("[INFO] Allowed chat ids: %s", allowed_chat_ids)


def restricted_to_allowed_chats(handler):
    """Wrap a handler so it only runs in private DMs or allow-listed chats.

    In any other group/supergroup the bot stays silent and leaves the chat, so a
    single config is the only source of where the bot is active.
    """

    @wraps(handler)
    async def wrapper(update, context, *args, **kwargs):
        chat = update.effective_chat
        if chat is None:
            return None

        # Direct messages are always allowed — that's where /start and /help live.
        if chat.type == ChatType.PRIVATE or chat.id in allowed_chat_ids:
            return await handler(update, context, *args, **kwargs)

        logger.info("[INFO] Ignoring update from non-allowed chat %s (%s)", chat.id, chat.type)
        try:
            await chat.leave()
        except TelegramError as exc:
            logger.debug("[DEBUG] Could not leave non-allowed chat %s: %s", chat.id, exc)
        return None

    return wrapper
