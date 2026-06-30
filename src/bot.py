# -*- coding: utf-8 -*-
"""Global BOT command."""

import logging

import sentry_sdk
from telegram import Update
from telegram.ext import Application, ChatMemberHandler, CommandHandler, MessageHandler, filters

from core.allowlist import resolve_allowlist, restricted_to_allowed_chats
from core.config import SENTRY_DSN, TELEGRAM_BOT_TOKEN
from core.storage import get_storage
from handlers.admin_handlers import ban_user, kick_user, mute_user, unban_user, unmute_user
from handlers.flood_control import flood_control
from handlers.info_handlers import help_command, start
from handlers.media_moderation import build_media_filter, moderate_media
from handlers.message_moderation import moderate_message
from handlers.service_handlers import delete_bad_message, errors_logging, ping
from handlers.user_handlers import greet_chat_members
from handlers.warn_handlers import unwarn_user, warn_user, warns_list

# Logging is configured once in core.config (imported above).
logger = logging.getLogger(__name__)


def main() -> None:
    sentry_sdk.init(SENTRY_DSN, traces_sample_rate=1.0)

    # Open the database and create the schema before any update is handled.
    storage = get_storage()
    logger.info("[INFO] Storage ready at %s", storage.path)

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
    # Ban user manual (optional duration: /ban 1d)
    application.add_handler(CommandHandler("ban", restricted_to_allowed_chats(ban_user)))
    # Unban user manual
    application.add_handler(CommandHandler("unban", restricted_to_allowed_chats(unban_user)))
    # Kick user (ban + immediate unban)
    application.add_handler(CommandHandler("kick", restricted_to_allowed_chats(kick_user)))
    # Mute user manual
    application.add_handler(CommandHandler("mute", restricted_to_allowed_chats(mute_user)))
    # Unmute user manual
    application.add_handler(CommandHandler("unmute", restricted_to_allowed_chats(unmute_user)))
    # Warn user (auto-punish at the limit)
    application.add_handler(CommandHandler("warn", restricted_to_allowed_chats(warn_user)))
    # Show a user's warn history
    application.add_handler(CommandHandler("warns", restricted_to_allowed_chats(warns_list)))
    # Remove a user's last warn
    application.add_handler(CommandHandler("unwarn", restricted_to_allowed_chats(unwarn_user)))

    # Filter links/forwards/mentions from newcomers (also re-checks edits)
    application.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.FORWARDED) & ~filters.COMMAND,
            restricted_to_allowed_chats(moderate_message),
        )
    )

    # Welcome message
    application.add_handler(ChatMemberHandler(restricted_to_allowed_chats(greet_chat_members), ChatMemberHandler.CHAT_MEMBER))

    # Delete configured media types from non-admins (notifies the author)
    media_filter = build_media_filter()
    if media_filter is not None:
        application.add_handler(MessageHandler(media_filter, restricted_to_allowed_chats(moderate_media)))

    # Delete left chat member service message
    application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, restricted_to_allowed_chats(delete_bad_message)))
    # Delete new chat member service message
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, restricted_to_allowed_chats(delete_bad_message)))

    # Flood control runs in its own group so it counts every message regardless
    # of which group-0 handler also processes it.
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, restricted_to_allowed_chats(flood_control)),
        group=1,
    )

    application.add_error_handler(errors_logging)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
