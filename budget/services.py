"""
Currency conversion service and budget initialization helpers.
"""
import time
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported currencies
# ---------------------------------------------------------------------------

SUPPORTED_CURRENCIES = [
    {"code": "USD", "name": "US Dollar", "symbol": "$"},
    {"code": "EUR", "name": "Euro", "symbol": "€"},
    {"code": "RUB", "name": "Russian Ruble", "symbol": "₽"},
    {"code": "GBP", "name": "British Pound", "symbol": "£"},
    {"code": "UAH", "name": "Ukrainian Hryvnia", "symbol": "₴"},
    {"code": "KZT", "name": "Kazakhstani Tenge", "symbol": "₸"},
    {"code": "BYN", "name": "Belarusian Ruble", "symbol": "Br"},
    {"code": "CNY", "name": "Chinese Yuan", "symbol": "¥"},
    {"code": "JPY", "name": "Japanese Yen", "symbol": "¥"},
    {"code": "TRY", "name": "Turkish Lira", "symbol": "₺"},
    {"code": "AED", "name": "UAE Dirham", "symbol": "د.إ"},
    {"code": "CHF", "name": "Swiss Franc", "symbol": "Fr"},
    {"code": "PLN", "name": "Polish Zloty", "symbol": "zł"},
    {"code": "CZK", "name": "Czech Koruna", "symbol": "Kč"},
    {"code": "SEK", "name": "Swedish Krona", "symbol": "kr"},
    {"code": "CAD", "name": "Canadian Dollar", "symbol": "CA$"},
    {"code": "AUD", "name": "Australian Dollar", "symbol": "A$"},
    {"code": "INR", "name": "Indian Rupee", "symbol": "₹"},
    {"code": "BRL", "name": "Brazilian Real", "symbol": "R$"},
    {"code": "MXN", "name": "Mexican Peso", "symbol": "$"},
]

SUPPORTED_CURRENCY_CODES = {c["code"] for c in SUPPORTED_CURRENCIES}

# ---------------------------------------------------------------------------
# Exchange rate cache (in-memory, 1 hour TTL)
# ---------------------------------------------------------------------------

_rate_cache: dict[str, tuple[float, dict]] = {}  # {base: (timestamp, {code: rate})}
_CACHE_TTL = 3600  # seconds


def _get_rates(base_currency: str) -> Optional[dict]:
    """
    Fetch exchange rates from ExchangeRate-API.
    Returns dict {currency_code: rate} where rate = how many units of currency
    you get for 1 unit of base_currency.
    Falls back to {base: 1.0} if no API key is configured.
    """
    cached = _rate_cache.get(base_currency)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    api_key = settings.EXCHANGE_RATE_API_KEY
    if not api_key:
        logger.warning('EXCHANGE_RATE_API_KEY not set — using 1:1 conversion.')
        return {base_currency: 1.0}

    try:
        url = f'https://v6.exchangerate-api.com/v6/{api_key}/latest/{base_currency}'
        with httpx.Client(timeout=10) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get('result') != 'success':
            logger.error('ExchangeRate-API error: %s', data)
            return None

        rates = data['conversion_rates']
        _rate_cache[base_currency] = (time.time(), rates)
        return rates

    except Exception as exc:
        logger.error('Failed to fetch exchange rates: %s', exc)
        return None


def convert_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
) -> Decimal:
    """
    Convert `amount` from `from_currency` to `to_currency`.
    Returns the converted amount rounded to 2 decimal places.
    Falls back to the original amount if conversion fails.
    """
    if from_currency == to_currency:
        return amount

    rates = _get_rates(to_currency)
    if rates is None:
        logger.warning('Could not get rates, using original amount.')
        return amount

    # rates[X] = how many X you get per 1 to_currency
    # We need: how many to_currency per 1 from_currency
    # => 1 from_currency = rates[from_currency] to_currency... no.
    #
    # _get_rates(to_currency) gives rates relative to to_currency as base.
    # rates['USD'] when base=RUB means 1 RUB = rates['USD'] USD.
    # So: amount_in_to = amount_in_from * rates[from_currency]
    #
    # Wait — ExchangeRate-API latest/{base} returns:
    #   rates[X] = how many X per 1 {base}
    # So if base=RUB, rates['USD'] = 0.011 means 1 RUB = 0.011 USD.
    # We want: amount_original (from_currency) -> to_currency
    # Step 1: convert from_currency to RUB (base): amount / rates[from_currency]
    #   No, that's wrong. We have base=to_currency.
    #   rates[from_currency] = how many from_currency per 1 to_currency
    #   So: amount_to = amount_from / rates[from_currency]

    rate = rates.get(from_currency)
    if rate is None or rate == 0:
        logger.warning('No rate for %s -> %s', from_currency, to_currency)
        return amount

    converted = Decimal(str(amount)) / Decimal(str(rate))
    return converted.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Default categories
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES = [
    # Expenses
    {"name": "Food",          "icon": "🍔"},
    {"name": "Transport",     "icon": "🚗"},
    {"name": "Housing",       "icon": "🏠"},
    {"name": "Health",        "icon": "💊"},
    {"name": "Entertainment", "icon": "🎬"},
    {"name": "Clothes",       "icon": "👗"},
    {"name": "Education",     "icon": "📚"},
    {"name": "Other expense", "icon": "📦"},
    # Income
    {"name": "Salary",        "icon": "💼"},
    {"name": "Freelance",     "icon": "💻"},
    {"name": "Gift",          "icon": "🎁"},
    {"name": "Other income",  "icon": "💰"},
]


def create_default_categories(budget) -> None:
    """Create default categories for a newly created budget."""
    from budget.models import Category

    Category.objects.bulk_create([
        Category(
            budget=budget,
            name=cat["name"],
            icon=cat["icon"],
            is_default=True,
            created_by=None,
        )
        for cat in DEFAULT_CATEGORIES
    ], ignore_conflicts=True)


# ---------------------------------------------------------------------------
# Chat ID extraction
# ---------------------------------------------------------------------------

def get_chat_id(telegram_data: dict) -> int:
    """
    Extract the budget's chat_id from verified Telegram initData.
    - Group/supergroup chats: use chat.id (negative number)
    - Private chat with bot: check UserBudgetLink first (shared/invited budget),
      then fall back to user.id (personal budget)
    """
    chat = telegram_data.get('chat')
    if chat:
        return int(chat['id'])

    user_id = int(telegram_data['user']['id'])

    # Check if this user joined a shared budget via invite
    try:
        from budget.models import UserBudgetLink
        link = UserBudgetLink.objects.select_related('budget').get(user_id=user_id)
        return link.budget.chat_id
    except Exception:
        pass

    return user_id


def get_user_display_name(user: dict) -> str:
    """Build a display name from Telegram user object."""
    first = user.get('first_name', '')
    last = user.get('last_name', '')
    username = user.get('username', '')
    full = f'{first} {last}'.strip()
    return full or username or str(user.get('id', 'Unknown'))
