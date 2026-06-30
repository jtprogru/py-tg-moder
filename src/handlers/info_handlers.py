import logging

from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes

from core.config import CHAT_RULES_URL, MAIN_GROUP

logger = logging.getLogger(__name__)

# Commands every chat member can use.
_USER_HELP = (
    "<b>Я бот-модератор этого чата.</b>\n\n"
    "Доступные команды:\n"
    "• /help — это сообщение\n"
    "• /ping — проверить, что бот жив\n\n"
    f'Пожалуйста, прочитай <a href="{CHAT_RULES_URL}">правила чата</a>.'
)

# Extra block shown only to chat administrators.
_ADMIN_HELP = (
    "\n\n<b>Команды модерации (ответом на сообщение пользователя):</b>\n"
    "• /ban — забанить автора\n"
    "• /unban — разбанить автора\n"
    "• /mute — замьютить автора\n"
    "• /unmute — снять мьют с автора\n"
    "• /warn [причина] — предупредить автора\n"
    "• /warns — история предупреждений автора\n"
    "• /unwarn — снять последнее предупреждение"
)


async def _is_chat_admin(update: Update) -> bool:
    """Return True if the command issuer is an administrator of the chat."""
    chat = update.effective_chat
    user = update.effective_user
    if chat is None or user is None or chat.type == ChatType.PRIVATE:
        return False
    admins = await chat.get_administrators()
    return user.id in {admin.user.id for admin in admins}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Briefly explain that this is a private moderation bot (mostly for DMs)."""
    chat_ref = f" {MAIN_GROUP}" if MAIN_GROUP else ""
    await update.effective_message.reply_text(
        f"Привет! Я приватный бот-модератор чата{chat_ref}.\n\nВ личке я почти ничего не умею — вся работа происходит в чате. Список команд: /help",
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the command list; administrators additionally see moderation commands."""
    text = _USER_HELP
    if await _is_chat_admin(update):
        text += _ADMIN_HELP
    await update.effective_message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
