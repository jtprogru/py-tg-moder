import logging

from telegram import Update, ParseMode
from telegram.ext import CallbackContext

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)
logger = logging.getLogger(__name__)


def delete_voices(update: Update, context: CallbackContext) -> None:
    """Delete all voice, video_note, location, left_chat_member, new_chat_members messages"""

    logger.debug(f'[DEBUG] Message from {update.message.from_user} with ID {update.message.from_user.id} was deleted')
    update.message.delete()


def ping(update: Update, context: CallbackContext) -> None:
    """Ping->Pong"""

    logger.debug(f'[DEBUG] Ping message from {update.message.from_user} with '
                 f'ID {update.message.from_user.id} was response')
    update.effective_message.reply_text("<b>pong</b>", parse_mode=ParseMode.HTML)
