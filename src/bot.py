# -*- coding: utf-8 -*-
"""Global BOT command."""
import logging
from telegram import Update
from telegram.ext import ChatMemberHandler, CommandHandler, Filters, MessageHandler, Updater

from core.config import TELEGRAM_BOT_TOKEN
from handlers.admin_handlers import ban_user, mute_user, unban_user, unmute_user
from handlers.service_handlers import delete_bad_message, errors_logging, ping
from handlers.user_handlers import greet_chat_members

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG)

logger = logging.getLogger(__name__)


if __name__ == "__main__":
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Keep track of which chats the bot is in
    dispatcher.add_handler(CommandHandler("ping", ping))
    # Ban user manual
    dispatcher.add_handler(CommandHandler("ban", ban_user))
    # Unban user manual
    dispatcher.add_handler(CommandHandler("ban", unban_user))
    # Mute user manual
    dispatcher.add_handler(CommandHandler("mute", mute_user))
    # Unmute user manual
    dispatcher.add_handler(CommandHandler("mute", unmute_user))

    # Welcome message
    dispatcher.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))
    # Delete voice message
    dispatcher.add_handler(MessageHandler(Filters.voice, delete_bad_message))
    # Delete video message
    dispatcher.add_handler(MessageHandler(Filters.video, delete_bad_message))
    # Delete locations
    dispatcher.add_handler(MessageHandler(Filters.location, delete_bad_message))
    # Delete video note
    dispatcher.add_handler(MessageHandler(Filters.video_note, delete_bad_message))
    # Delete left chat member
    dispatcher.add_handler(MessageHandler(Filters.status_update.left_chat_member, delete_bad_message))
    # Delete new chat member
    dispatcher.add_handler(MessageHandler(Filters.status_update.new_chat_members, delete_bad_message))
    # TODO: This is work?
    dispatcher.add_error_handler(errors_logging)

    updater.start_polling(allowed_updates=Update.ALL_TYPES)

    updater.idle()
