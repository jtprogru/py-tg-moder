# -*- coding: utf-8 -*-
"""Global BOT command."""

import asyncio
import logging

import sentry_sdk
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ChatMemberHandler, CommandHandler, MessageHandler, filters

from core.allowlist import resolve_allowlist, restricted_to_allowed_chats
from core.config import SENTRY_DSN, TELEGRAM_BOT_TOKEN, WEB_ENABLED, WEB_HOST, WEB_PORT, WEB_SESSION_SECRET
from core.retention import start_retention
from core.storage import get_storage
from handlers.admin_handlers import ban_user, kick_user, mute_user, unban_user, unmute_user
from handlers.captcha import captcha_callback, rearm_captchas
from handlers.flood_control import flood_control
from handlers.info_handlers import help_command, start
from handlers.media_moderation import build_media_filter, moderate_media
from handlers.message_moderation import moderate_message
from handlers.service_handlers import delete_bad_message, errors_logging, ping
from handlers.user_cache import cache_seen_user
from handlers.user_handlers import greet_chat_members
from handlers.warn_handlers import unwarn_user, warn_user, warns_list

# Logging is configured once in core.config (imported above).
logger = logging.getLogger(__name__)


async def _post_init(application) -> None:
    """Runtime setup once the bot is ready: resolve the allowlist, rearm any
    captcha challenges that were pending when the process last stopped, and
    start the daily retention purge."""
    await resolve_allowlist(application)
    await rearm_captchas(application)
    start_retention(application)


def build_application() -> Application:
    """Assemble the PTB application with every handler registered."""
    # Resolve the configured allowlist (@usernames -> ids) once the bot is ready.
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()

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

    # Welcome message / captcha challenge on join
    application.add_handler(ChatMemberHandler(restricted_to_allowed_chats(greet_chat_members), ChatMemberHandler.CHAT_MEMBER))
    # Captcha button taps
    application.add_handler(CallbackQueryHandler(restricted_to_allowed_chats(captcha_callback), pattern=r"^captcha:"))

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

    # Cache @username -> id for everyone we see, so commands can target by name.
    application.add_handler(
        MessageHandler(filters.ALL & ~filters.StatusUpdate.ALL, restricted_to_allowed_chats(cache_seen_user)),
        group=2,
    )

    application.add_error_handler(errors_logging)
    return application


async def _run_with_web(application: Application) -> None:
    """Run polling and the dashboard web server on one event loop.

    Manual PTB lifecycle (the documented pattern for running next to another
    asyncio framework): uvicorn owns the signals, so ``server.serve()`` returns
    on SIGINT/SIGTERM and the bot is stopped cleanly afterwards. The web app
    gets the live Application so routes can reach the Bot API and storage.
    """
    import uvicorn

    from web.app import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(application), host=WEB_HOST, port=WEB_PORT, log_level="info"))
    async with application:  # initialize() / shutdown()
        # post_init is only called by run_polling, so mirror it here.
        if application.post_init:
            await application.post_init(application)
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await application.start()
        logger.info("[INFO] Web dashboard listening on %s:%s", WEB_HOST, WEB_PORT)
        await server.serve()
        await application.updater.stop()
        await application.stop()


def main() -> None:
    sentry_sdk.init(SENTRY_DSN, traces_sample_rate=1.0)

    # Open the database and create the schema before any update is handled.
    storage = get_storage()
    logger.info("[INFO] Storage ready at %s", storage.path)

    application = build_application()
    if WEB_ENABLED:
        if not WEB_SESSION_SECRET:
            raise SystemExit("WEB_SESSION_SECRET is required when web.enabled is true")
        asyncio.run(_run_with_web(application))
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
