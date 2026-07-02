import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _update_ref(update: object) -> str:
    """A compact, content-free reference to an update for logs.

    Avoids dumping the whole update (message text, user data) into logs/Sentry;
    the full payload is only emitted at DEBUG level.
    """
    if isinstance(update, Update):
        return f"update_id={update.update_id}"
    return type(update).__name__


async def delete_bad_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete service messages (members joining/leaving). Media is handled by media_moderation."""

    logger.debug(f"[DEBUG] Message from {update.message.from_user} with ID {update.message.from_user.id} was deleted")
    await update.message.delete()


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ping->Pong"""

    logger.debug(f"[DEBUG] Ping message from {update.message.from_user} with ID {update.message.from_user.id} was response")
    await update.effective_message.reply_text("<b>pong</b>", parse_mode=ParseMode.HTML)


async def errors_logging(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Errors logging"""

    error = context.error
    message = getattr(error, "message", str(error))
    if message != "Message is not modified":
        logger.warning('Update %s caused error "%s"', _update_ref(update), error)
    # Full update payload (may contain message text/user data) only under DEBUG.
    logger.debug("[DEBUG] Update that caused the error: %s", update)
    logger.error("[ERROR] %s", error, exc_info=error)
