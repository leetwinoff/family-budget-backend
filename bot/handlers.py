import os
import logging

import httpx
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Localised strings
# ---------------------------------------------------------------------------

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

SHARE_TEXT = {
    'en': (
        "🔗 *Share your budget*\n\n"
        "Send this link to the person you want to share your budget with.\n"
        "Once they tap it, you'll both see the same transactions.\n\n"
        "{link}\n\n"
        "_Link is valid for 7 days._"
    ),
    'ru': (
        "🔗 *Поделиться бюджетом*\n\n"
        "Отправьте эту ссылку человеку, с которым хотите вести общий бюджет.\n"
        "После перехода по ней вы оба будете видеть одни и те же транзакции.\n\n"
        "{link}\n\n"
        "_Ссылка действительна 7 дней._"
    ),
}

JOIN_SUCCESS_TEXT = {
    'en': (
        "✅ *You've joined the shared budget!*\n\n"
        "From now on, when you open the app here, you'll see the shared budget.\n"
        "Tap the button to get started."
    ),
    'ru': (
        "✅ *Вы присоединились к общему бюджету!*\n\n"
        "Теперь при открытии приложения вы будете видеть общий бюджет.\n"
        "Нажмите кнопку, чтобы начать."
    ),
}

JOIN_SELF_TEXT = {
    'en': "ℹ️ This is your own invite link — share it with someone else.",
    'ru': "ℹ️ Это ваша собственная ссылка — поделитесь ею с кем-то другим.",
}

JOIN_INVALID_TEXT = {
    'en': "❌ This invite link is invalid or has expired. Ask the budget owner to send a new one.",
    'ru': "❌ Ссылка недействительна или устарела. Попросите владельца бюджета прислать новую.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _api_url() -> str:
    return os.environ.get('API_URL', 'https://family-budget-api-af0c.onrender.com')


def _bot_token() -> str:
    return os.environ.get('TELEGRAM_BOT_TOKEN', '')


# ---------------------------------------------------------------------------
# /start — also handles deep links: /start join_<token>
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /budget commands, including invite deep links."""
    args = context.args or []

    if args and args[0].startswith('join_'):
        token = args[0][len('join_'):]
        await _handle_join(update, context, token)
        return

    lang = _get_lang(update.effective_user)
    await update.message.reply_text(
        text=WELCOME_TEXT[lang],
        reply_markup=_build_keyboard(lang),
        parse_mode='Markdown',
    )


# ---------------------------------------------------------------------------
# /share — generate an invite link for the user's budget
# ---------------------------------------------------------------------------

async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a shareable invite link for the current user's budget."""
    user = update.effective_user
    lang = _get_lang(user)

    # Only meaningful in private chats (group members share by being in the group)
    if update.effective_chat.type != 'private':
        hint = {
            'en': "ℹ️ The /share command works in private chat with the bot. Open a DM and try again.",
            'ru': "ℹ️ Команда /share работает в личном чате с ботом. Откройте личные сообщения и попробуйте снова.",
        }
        await update.message.reply_text(hint[lang])
        return

    bot_me = await context.bot.get_me()
    bot_username = bot_me.username

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f'{_api_url()}/api/bot/invite',
                json={'user_id': user.id, 'bot_username': bot_username},
                headers={'X-Bot-Token': _bot_token()},
            )
        logger.info('invite response %s: %s', resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error('Failed to create invite for user %s: %s', user.id, exc)
        err = {
            'en': "⚠️ Could not generate an invite link right now. Please try again later.",
            'ru': "⚠️ Не удалось создать ссылку. Попробуйте позже.",
        }
        await update.message.reply_text(err[lang])
        return

    link = data['link']
    await update.message.reply_text(
        text=SHARE_TEXT[lang].format(link=link),
        parse_mode='Markdown',
        disable_web_page_preview=True,
    )


# ---------------------------------------------------------------------------
# Deep-link join handler (called from cmd_start)
# ---------------------------------------------------------------------------

async def _handle_join(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str) -> None:
    user = update.effective_user
    lang = _get_lang(user)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f'{_api_url()}/api/bot/join',
                json={'user_id': user.id, 'token': token},
                headers={'X-Bot-Token': _bot_token()},
            )
        data = resp.json()
    except Exception as exc:
        logger.error('Join request failed for user %s token %s: %s', user.id, token, exc)
        await update.message.reply_text(JOIN_INVALID_TEXT[lang])
        return

    if resp.status_code == 400 and data.get('error') == 'already_owner':
        await update.message.reply_text(JOIN_SELF_TEXT[lang])
        return

    if resp.status_code != 200:
        await update.message.reply_text(JOIN_INVALID_TEXT[lang])
        return

    await update.message.reply_text(
        text=JOIN_SUCCESS_TEXT[lang],
        reply_markup=_build_keyboard(lang),
        parse_mode='Markdown',
    )


# ---------------------------------------------------------------------------
# Bot added to / removed from a chat
# ---------------------------------------------------------------------------

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
