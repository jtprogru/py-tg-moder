# -*- coding: utf-8 -*-
"""Global BOT command."""
import logging
from telegram import Update
from telegram.ext import (
    Filters,
    Updater,
    CommandHandler,
    ChatMemberHandler,
    MessageHandler
)

from core.config import TELEGRAM_BOT_TOKEN
from handlers.service_handlers import delete_voices, ping
from handlers.user_handlers import greet_chat_members
from handlers.admin_handlers import ban_user, mute_user


# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG
)

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    updater = Updater(TELEGRAM_BOT_TOKEN)
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # Keep track of which chats the bot is in
    # dispatcher.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    dispatcher.add_handler(CommandHandler("ping", ping))
    # Ban user manual
    dispatcher.add_handler(CommandHandler("ban", ban_user))
    # Mute user manual
    dispatcher.add_handler(CommandHandler("mute", mute_user))

    # Handle members joining/leaving chats.
    dispatcher.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))
    # Handle join/leaving message
    dispatcher.add_handler(
        MessageHandler(
            Filters.voice | Filters.video | Filters.location | Filters.video_note |
            Filters.status_update.left_chat_member | Filters.status_update.new_chat_members,
            delete_voices
        )
    )

    updater.start_polling(allowed_updates=Update.ALL_TYPES)

    updater.idle()
