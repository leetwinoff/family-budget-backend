import os
import json
import logging

import anthropic
import httpx
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    MenuButtonWebApp,
    WebAppInfo,
    InputMediaPhoto,
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

GROUP_READY_TEXT = {
    'en': (
        "👋 *Family Budget* is ready!\n\n"
        "Track shared income and expenses with everyone in this chat.\n"
        "Tap the *💰 Open Budget* button next to the message input to open the app."
    ),
    'ru': (
        "👋 *Семейный бюджет* готов к работе!\n\n"
        "Ведите общий учёт доходов и расходов вместе с участниками чата.\n"
        "Нажмите кнопку *💰 Открыть бюджет* рядом с полем ввода, чтобы открыть приложение."
    ),
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

WISH_PARSE_ERROR_TEXT = {
    'en': "❌ Could not parse this link. The page may require login or is not a product page.",
    'ru': "❌ Не удалось разобрать эту ссылку. Страница может требовать входа или это не страница товара.",
}

WISH_FETCH_ERROR_TEXT = {
    'en': "❌ Could not open this link. Please check that it's accessible.",
    'ru': "❌ Не удалось открыть эту ссылку. Убедитесь, что она доступна.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_lang(user) -> str:
    if user and getattr(user, 'language_code', None) == 'ru':
        return 'ru'
    return 'en'


def _webapp_url(chat_id: int | None = None) -> str:
    frontend_url = os.environ.get('FRONTEND_URL', '')
    return f'{frontend_url}?chat_id={chat_id}' if chat_id else frontend_url


def _build_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Inline WebApp button — for private chats only."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            text=BUTTON_TEXT[lang],
            web_app=WebAppInfo(url=_webapp_url()),
        )
    ]])


async def _set_group_menu_button(bot, chat_id: int, lang: str) -> None:
    """Set the persistent menu button for a group chat."""
    await bot.set_chat_menu_button(
        chat_id=chat_id,
        menu_button=MenuButtonWebApp(
            text=BUTTON_TEXT[lang],
            web_app=WebAppInfo(url=_webapp_url(chat_id=chat_id)),
        ),
    )


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
    if chat.type in ('group', 'supergroup'):
        await _set_group_menu_button(context.bot, chat.id, lang)
        msg = await update.message.reply_text(
            text=GROUP_READY_TEXT[lang],
            parse_mode='Markdown',
        )
        try:
            await context.bot.pin_chat_message(
                chat_id=chat.id,
                message_id=msg.message_id,
                disable_notification=True,
            )
        except Exception as exc:
            logger.warning('Could not pin message in chat %s: %s', chat.id, exc)
    else:
        await update.message.reply_text(
            text=WELCOME_TEXT[lang],
            reply_markup=_build_keyboard(lang),
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
        await _set_group_menu_button(context.bot, result.chat.id, lang)
        msg = await context.bot.send_message(
            chat_id=result.chat.id,
            text=GROUP_READY_TEXT[lang],
            parse_mode='Markdown',
        )
        await context.bot.pin_chat_message(
            chat_id=result.chat.id,
            message_id=msg.message_id,
            disable_notification=True,
        )
    except Exception as exc:
        logger.warning('Could not send/pin welcome message to chat %s: %s', result.chat.id, exc)


# ---------------------------------------------------------------------------
# Wish URL handler — parses marketplace links and adds to wishlist
# ---------------------------------------------------------------------------

_CLAUDE_SYSTEM = (
    "You are a product data extractor. Given raw HTML from a marketplace or shop page, "
    "extract product details and return ONLY valid JSON with these fields:\n"
    "  name: string (product title, max 256 chars)\n"
    "  description: string (short description, max 300 chars, empty string if not found)\n"
    "  price: number or null (numeric value only, no currency symbols)\n"
    "  currency: string (3-letter ISO code like USD/EUR/UAH, empty string if not found)\n"
    "  image_url: string (absolute URL to the main product image, empty string if not found)\n\n"
    "If this is not a product page or you cannot extract a name, return: {\"error\": \"not_a_product\"}"
)

_FETCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


async def _fetch_page_html(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=15,
            headers=_FETCH_HEADERS,
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        # Truncate to ~80k chars to stay within Claude's context
        return resp.text[:80_000]
    except Exception as exc:
        logger.warning('Failed to fetch URL %s: %s', url, exc)
        return None


def _parse_with_claude(html: str) -> dict | None:
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.error('ANTHROPIC_API_KEY is not set')
        return None

    client = anthropic.Anthropic(api_key=api_key)
    try:
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=512,
            system=_CLAUDE_SYSTEM,
            messages=[{'role': 'user', 'content': html}],
        )
        raw = message.content[0].text.strip()
        # Strip markdown code fences if Claude wrapped the JSON
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        data = json.loads(raw)
        if data.get('error') == 'not_a_product':
            return None
        return data
    except Exception as exc:
        logger.warning('Claude parsing failed: %s', exc)
        return None


async def on_wish_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered when a group message contains a URL entity."""
    message = update.message
    if not message or not message.entities:
        return

    chat = update.effective_chat
    if chat.type not in ('group', 'supergroup'):
        return

    # Extract the first URL from message entities
    url: str | None = None
    for entity in message.entities:
        if entity.type in ('url', 'text_link'):
            url = entity.url if entity.type == 'text_link' else message.text[entity.offset:entity.offset + entity.length]
            break

    if not url:
        return

    lang = _get_lang(update.effective_user)

    # Fetch the page
    html = await _fetch_page_html(url)
    if html is None:
        await message.reply_text(WISH_FETCH_ERROR_TEXT[lang], parse_mode='HTML')
        return

    # Parse with Claude (sync call — run in executor to avoid blocking the event loop)
    import asyncio
    loop = asyncio.get_event_loop()
    product = await loop.run_in_executor(None, _parse_with_claude, html)

    if product is None:
        await message.reply_text(WISH_PARSE_ERROR_TEXT[lang], parse_mode='HTML')
        return

    # Post wish to backend
    user = update.effective_user
    payload = {
        'chat_id': chat.id,
        'user_id': user.id,
        'name': product.get('name', '')[:256],
        'description': product.get('description', ''),
        'link': url,
        'price': product.get('price'),
        'currency': product.get('currency', ''),
        'image_url': product.get('image_url', ''),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f'{_api_url()}/api/bot/wish',
                json=payload,
                headers={'X-Bot-Token': _bot_token()},
            )
        if resp.status_code not in (200, 201):
            logger.error('BotAddWish returned %s: %s', resp.status_code, resp.text)
            await message.reply_text(WISH_PARSE_ERROR_TEXT[lang], parse_mode='HTML')
            return
    except Exception as exc:
        logger.error('BotAddWish request failed: %s', exc)
        await message.reply_text(WISH_PARSE_ERROR_TEXT[lang], parse_mode='HTML')
        return

    # Build caption: name as hyperlink + price
    name = product.get('name', 'Item')[:256]
    price = product.get('price')
    currency = product.get('currency', '')
    image_url = product.get('image_url', '')

    price_line = f'\n💰 {price} {currency}'.rstrip() if price else ''
    caption = f'<a href="{url}">{name}</a>{price_line}'

    # Send photo if available, otherwise send text
    if image_url:
        try:
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=image_url,
                caption=caption,
                parse_mode='HTML',
            )
            return
        except Exception as exc:
            logger.warning('send_photo failed for %s: %s', image_url, exc)

    await message.reply_text(caption, parse_mode='HTML', disable_web_page_preview=False)
