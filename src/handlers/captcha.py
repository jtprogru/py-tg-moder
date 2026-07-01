"""Button captcha for new chat members.

On join a newcomer is muted and shown a button. Tapping it within the timeout
unmutes them and posts the welcome; otherwise they are kicked or banned. A CAS
hit never reaches here — those are banned outright before the challenge.

Pending challenges are persisted (so a restart mid-challenge does not leave a
newcomer muted forever with no button) and the timeout is an asyncio task (no
job-queue dependency). ``rearm_captchas`` reloads them on startup. The mute is
permanent until the user passes — never fail-open, or an automated bot would
gain write access just by waiting.
"""

import asyncio
import time
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import ContextTypes

from core import config
from core.config import CHAT_RULES_URL, logger
from core.storage import get_storage

from .admin_handlers import MUTE_PERMISSIONS, UNMUTE_PERMISSIONS

# (chat_id, user_id) -> challenge message_id, so it can be removed on pass/timeout.
_pending: dict = {}
# Strong refs to in-flight timeout tasks so they are not garbage-collected.
_tasks: set = set()


def _key(chat_id: int, user_id: int) -> tuple:
    return (chat_id, user_id)


def _track(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def start_challenge(chat, user: User) -> None:
    """Mute the newcomer and post the captcha button."""
    try:
        await chat.restrict_member(user_id=user.id, permissions=MUTE_PERMISSIONS)
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Could not mute newcomer %s for captcha: %s", user.id, exc)
        return

    await asyncio.to_thread(get_storage().add_mute, chat.id, user.id, None)

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Я не бот ✅", callback_data=f"captcha:{user.id}")]])
    try:
        message = await chat.send_message(
            f"{user.mention_html()}, подтверди, что ты не бот — нажми кнопку в течение {config.CAPTCHA_TIMEOUT} сек.",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Could not send captcha to %s: %s", user.id, exc)
        return

    deadline = int(time.time()) + config.CAPTCHA_TIMEOUT
    _pending[_key(chat.id, user.id)] = message.message_id
    await asyncio.to_thread(get_storage().add_captcha, chat.id, user.id, message.message_id, deadline)
    _track(asyncio.create_task(_expire(chat, user.id)))
    logger.info("[INFO] Captcha started for user %s", user.id)


async def _expire(chat, user_id: int, delay: Optional[int] = None) -> None:
    """Wait out the timeout, then punish the user if they still haven't passed."""
    await asyncio.sleep(config.CAPTCHA_TIMEOUT if delay is None else delay)
    await _punish_if_pending(chat, user_id)


async def _punish_if_pending(chat, user_id: int) -> None:
    """Kick/ban the user and clean up, unless they already passed in the meantime."""
    message_id = _pending.pop(_key(chat.id, user_id), None)
    if message_id is None:
        return  # already passed
    await asyncio.to_thread(get_storage().remove_captcha, chat.id, user_id)

    try:
        await chat.delete_message(message_id)
    except BadRequest, Forbidden:
        pass

    try:
        await chat.ban_member(user_id=user_id)
        if config.CAPTCHA_FAIL_ACTION == "kick":
            # Kick = ban + unban, so the user may rejoin and try again.
            await chat.unban_member(user_id=user_id)
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Captcha fail-action for %s failed: %s", user_id, exc)
    logger.info("[INFO] Captcha timed out for user %s (action=%s)", user_id, config.CAPTCHA_FAIL_ACTION)


async def rearm_captchas(application) -> None:
    """Reload persisted captcha challenges on startup and rearm their timeouts.

    A challenge whose deadline has already passed is punished immediately;
    otherwise a fresh timeout is scheduled for the remaining time. Chats we can
    no longer reach are dropped so a stale row can't wedge startup.
    """
    bot = application.bot
    rows = await asyncio.to_thread(get_storage().list_captchas)
    now = int(time.time())
    for row in rows:
        chat_id, user_id, message_id, deadline = row["chat_id"], row["user_id"], row["message_id"], row["deadline"]
        try:
            chat = await bot.get_chat(chat_id)
        except TelegramError as exc:
            logger.warning("[WARN] Dropping captcha for %s in unreachable chat %s: %s", user_id, chat_id, exc)
            await asyncio.to_thread(get_storage().remove_captcha, chat_id, user_id)
            continue
        _pending[_key(chat_id, user_id)] = message_id
        remaining = max(0, deadline - now)
        _track(asyncio.create_task(_expire(chat, user_id, delay=remaining)))
        logger.info("[INFO] Rearmed captcha for user %s in chat %s (%ss left)", user_id, chat_id, remaining)


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the button tap: only the challenged user can pass."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None:
        return

    target_id = _parse_target(query.data)
    if target_id is None:
        await query.answer()
        return

    if query.from_user.id != target_id:
        await query.answer("Эта кнопка не для тебя 🙂")
        return

    message_id = _pending.pop(_key(chat.id, target_id), None)
    await asyncio.to_thread(get_storage().remove_captcha, chat.id, target_id)

    try:
        await chat.restrict_member(user_id=target_id, permissions=UNMUTE_PERMISSIONS)
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Could not unmute %s after captcha: %s", target_id, exc)
    await asyncio.to_thread(get_storage().remove_mute, chat.id, target_id)

    await query.answer("Спасибо! Доступ открыт.")
    if message_id is not None:
        try:
            await chat.delete_message(message_id)
        except BadRequest, Forbidden:
            pass

    try:
        await chat.send_message(
            f'Хомячок {query.from_user.mention_html()} прошёл проверку.\n\nВелкам и прочти <a href="{CHAT_RULES_URL}">правила</a>!',
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except (BadRequest, Forbidden) as exc:
        logger.debug("[DEBUG] Could not send welcome after captcha: %s", exc)
    logger.info("[INFO] User %s passed captcha", target_id)


def _parse_target(data: Optional[str]) -> Optional[int]:
    if not data or ":" not in data:
        return None
    try:
        return int(data.split(":", 1)[1])
    except ValueError:
        return None
