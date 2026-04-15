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
        "👥 <b>How to share a budget</b>\n\n"
        "A shared budget belongs to a group chat — everyone in the group sees the same transactions.\n\n"
        "To set it up:\n"
        "1. Create a new Telegram group (or use an existing one)\n"
        "2. Add the people you want to share the budget with\n"
        "3. Add <b>@{bot_username}</b> to the group\n"
        "4. Open the app from that group — your shared budget is ready\n\n"
        "<i>Each group has its own independent budget.</i>"
    ),
    'ru': (
        "👥 <b>Как поделиться бюджетом</b>\n\n"
        "Общий бюджет привязан к групповому чату — все участники группы видят одни и те же транзакции.\n\n"
        "Как настроить:\n"
        "1. Создайте новую группу в Telegram (или используйте существующую)\n"
        "2. Добавьте людей, с которыми хотите вести общий бюджет\n"
        "3. Добавьте <b>@{bot_username}</b> в группу\n"
        "4. Откройте приложение из этой группы — общий бюджет готов\n\n"
        "<i>У каждой группы свой независимый бюджет.</i>"
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


def _build_keyboard(lang: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    frontend_url = os.environ.get('FRONTEND_URL', '')
    url = f'{frontend_url}?chat_id={chat_id}' if chat_id else frontend_url
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=BUTTON_TEXT[lang],
            web_app=WebAppInfo(url=url),
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
    chat = update.effective_chat
    # For group chats encode the chat_id in the URL so the Mini App
    # knows which budget to open (initData doesn't include chat for WebApp buttons)
    chat_id = chat.id if chat.type in ('group', 'supergroup') else None
    await update.message.reply_text(
        text=WELCOME_TEXT[lang],
        reply_markup=_build_keyboard(lang, chat_id=chat_id),
        parse_mode='Markdown',
    )


# ---------------------------------------------------------------------------
# /share — generate an invite link for the user's budget
# ---------------------------------------------------------------------------

async def cmd_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explain how to set up a shared group budget."""
    lang = _get_lang(update.effective_user)
    bot_me = await context.bot.get_me()
    await update.message.reply_text(
        text=SHARE_TEXT[lang].format(bot_username=bot_me.username),
        parse_mode='HTML',
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
            reply_markup=_build_keyboard(lang, chat_id=result.chat.id),
            parse_mode='Markdown',
        )
    except Exception as exc:
        logger.warning('Could not send welcome message to chat %s: %s', result.chat.id, exc)
