import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def delete_bad_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete all voice, video_note, location, left_chat_member, new_chat_members messages"""

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
        logger.warning('Update "%s" caused error "%s"', update, error)
    logger.error("[ERROR] %s", error, exc_info=error)
