# -*- coding: utf-8 -*-
"""Global BOT command."""

import logging

import sentry_sdk
from telegram import Update
from telegram.ext import Application, ChatMemberHandler, CommandHandler, MessageHandler, filters

from core.allowlist import resolve_allowlist, restricted_to_allowed_chats
from core.config import SENTRY_DSN, TELEGRAM_BOT_TOKEN
from handlers.admin_handlers import ban_user, mute_user, unban_user, unmute_user
from handlers.info_handlers import help_command, start
from handlers.service_handlers import delete_bad_message, errors_logging, ping
from handlers.user_handlers import greet_chat_members

# Logging is configured once in core.config (imported above).
logger = logging.getLogger(__name__)


def main() -> None:
    sentry_sdk.init(SENTRY_DSN, traces_sample_rate=1.0)

    # Resolve the configured allowlist (@usernames -> ids) once the bot is ready.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(resolve_allowlist).build()

    # Every handler is gated by the chat allowlist so the bot only acts in
    # configured chats (and private DMs); foreign chats are left silently.
    # Keep track of which chats the bot is in
    application.add_handler(CommandHandler("ping", restricted_to_allowed_chats(ping)))
    # Greeting / private intro
    application.add_handler(CommandHandler("start", restricted_to_allowed_chats(start)))
    # Command and rules reference
    application.add_handler(CommandHandler("help", restricted_to_allowed_chats(help_command)))
    # Ban user manual
    application.add_handler(CommandHandler("ban", restricted_to_allowed_chats(ban_user)))
    # Unban user manual
    application.add_handler(CommandHandler("unban", restricted_to_allowed_chats(unban_user)))
    # Mute user manual
    application.add_handler(CommandHandler("mute", restricted_to_allowed_chats(mute_user)))
    # Unmute user manual
    application.add_handler(CommandHandler("unmute", restricted_to_allowed_chats(unmute_user)))

    # Welcome message
    application.add_handler(ChatMemberHandler(restricted_to_allowed_chats(greet_chat_members), ChatMemberHandler.CHAT_MEMBER))
    # Delete voice message
    application.add_handler(MessageHandler(filters.VOICE, restricted_to_allowed_chats(delete_bad_message)))
    # Delete video message
    application.add_handler(MessageHandler(filters.VIDEO, restricted_to_allowed_chats(delete_bad_message)))
    # Delete locations
    application.add_handler(MessageHandler(filters.LOCATION, restricted_to_allowed_chats(delete_bad_message)))
    # Delete video note
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, restricted_to_allowed_chats(delete_bad_message)))
    # Delete left chat member
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, restricted_to_allowed_chats(delete_bad_message)))
    # Delete new chat member
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, restricted_to_allowed_chats(delete_bad_message)))

    application.add_error_handler(errors_logging)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
