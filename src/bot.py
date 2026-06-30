# -*- coding: utf-8 -*-
"""Global BOT command."""

import logging

import sentry_sdk
from telegram import Update
from telegram.ext import Application, ChatMemberHandler, CommandHandler, MessageHandler, filters

from core.config import SENTRY_DSN, TELEGRAM_BOT_TOKEN
from handlers.admin_handlers import ban_user, mute_user, unban_user, unmute_user
from handlers.service_handlers import delete_bad_message, errors_logging, ping
from handlers.user_handlers import greet_chat_members

# Logging is configured once in core.config (imported above).
logger = logging.getLogger(__name__)


def main() -> None:
    sentry_sdk.init(SENTRY_DSN, traces_sample_rate=1.0)

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Keep track of which chats the bot is in
    application.add_handler(CommandHandler("ping", ping))
    # Ban user manual
    application.add_handler(CommandHandler("ban", ban_user))
    # Unban user manual
    application.add_handler(CommandHandler("unban", unban_user))
    # Mute user manual
    application.add_handler(CommandHandler("mute", mute_user))
    # Unmute user manual
    application.add_handler(CommandHandler("unmute", unmute_user))

    # Welcome message
    application.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))
    # Delete voice message
    application.add_handler(MessageHandler(filters.VOICE, delete_bad_message))
    # Delete video message
    application.add_handler(MessageHandler(filters.VIDEO, delete_bad_message))
    # Delete locations
    application.add_handler(MessageHandler(filters.LOCATION, delete_bad_message))
    # Delete video note
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, delete_bad_message))
    # Delete left chat member
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_bad_message))
    # Delete new chat member
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, delete_bad_message))

    application.add_error_handler(errors_logging)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
