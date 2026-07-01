"""Button captcha for new chat members.

On join a newcomer is muted and shown a button. Tapping it within the timeout
unmutes them and posts the welcome; otherwise they are kicked or banned. A CAS
hit never reaches here — those are banned outright before the challenge.

Pending challenges live in memory and the timeout is an asyncio task (no
job-queue dependency). The mute is permanent until the user passes — never
fail-open, or an automated bot would gain write access just by waiting.
"""

import asyncio
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Update, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from core import config
from core.config import CHAT_RULES_URL, logger
from core.storage import get_storage

from .admin_handlers import MUTE_PERMISSIONS, UNMUTE_PERMISSIONS

# (chat_id, user_id) -> challenge Message, so it can be removed on pass/timeout.
_pending: dict = {}
# Strong refs to in-flight timeout tasks so they are not garbage-collected.
_tasks: set = set()


def _key(chat_id: int, user_id: int) -> tuple:
    return (chat_id, user_id)


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

    _pending[_key(chat.id, user.id)] = message
    task = asyncio.create_task(_expire(chat, user.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    logger.info("[INFO] Captcha started for user %s", user.id)


async def _expire(chat, user_id: int) -> None:
    """After the timeout, punish the user if they still haven't passed."""
    await asyncio.sleep(config.CAPTCHA_TIMEOUT)
    message = _pending.pop(_key(chat.id, user_id), None)
    if message is None:
        return  # already passed

    try:
        await message.delete()
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

    message = _pending.pop(_key(chat.id, target_id), None)

    try:
        await chat.restrict_member(user_id=target_id, permissions=UNMUTE_PERMISSIONS)
    except (BadRequest, Forbidden) as exc:
        logger.warning("[WARN] Could not unmute %s after captcha: %s", target_id, exc)
    await asyncio.to_thread(get_storage().remove_mute, chat.id, target_id)

    await query.answer("Спасибо! Доступ открыт.")
    if message is not None:
        try:
            await message.delete()
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
