import os
import logging

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus

logger = logging.getLogger(__name__)

WELCOME_TEXT = {
    'en': (
        "👋 *Family Budget* is ready!\n\n"
        "Track shared income and expenses with everyone in this chat.\n"
        "Tap the button below to open the app."
    ),
    'ru': (
        "👋 *Семейный бюджет* готов к работе!\n\n"
        "Ведите общий учёт доходов и расходов вместе с участниками чата.\n"
        "Нажмите кнопку ниже, чтобы открыть приложение."
    ),
}

BUTTON_TEXT = {
    'en': '💰 Open Budget',
    'ru': '💰 Открыть бюджет',
}


def _get_lang(user) -> str:
    if user and getattr(user, 'language_code', None) == 'ru':
        return 'ru'
    return 'en'


def _build_keyboard(lang: str) -> InlineKeyboardMarkup:
    frontend_url = os.environ.get('FRONTEND_URL', '')
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=BUTTON_TEXT[lang],
            web_app=WebAppInfo(url=frontend_url),
        )
    ]])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /budget commands."""
    lang = _get_lang(update.effective_user)
    await update.message.reply_text(
        text=WELCOME_TEXT[lang],
        reply_markup=_build_keyboard(lang),
        parse_mode='Markdown',
    )


async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Triggered when the bot's own membership status changes.
    Sends the welcome message when the bot is added to a group.
    """
    result = update.my_chat_member
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status

    # Bot was just added (was not member, now is member or admin)
    was_outside = old_status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
    now_inside = new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR)

    if not (was_outside and now_inside):
        return

    lang = _get_lang(result.from_user)
    try:
        await context.bot.send_message(
            chat_id=result.chat.id,
            text=WELCOME_TEXT[lang],
            reply_markup=_build_keyboard(lang),
            parse_mode='Markdown',
        )
    except Exception as exc:
        logger.warning('Could not send welcome message to chat %s: %s', result.chat.id, exc)
