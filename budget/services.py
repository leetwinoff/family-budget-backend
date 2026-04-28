"""
Currency conversion service and budget initialization helpers.
"""
import calendar
import time
import logging
from datetime import date, timedelta
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


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def get_current_period_range(period_type: str, period_start: date, period_days: int = None):
    """Return (start, end) date range for the current recurring budget period."""
    today = date.today()

    if period_type == 'weekly':
        weekday = period_start.weekday()
        days_since = (today.weekday() - weekday) % 7
        start = today - timedelta(days=days_since)
        return start, start + timedelta(days=7)

    if period_type == 'monthly':
        try:
            start = date(today.year, today.month, period_start.day)
        except ValueError:
            start = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        if today < start:
            start = _add_months(start, -1)
        return start, _add_months(start, 1)

    if period_type == 'yearly':
        try:
            start = date(today.year, period_start.month, period_start.day)
        except ValueError:
            start = date(today.year, period_start.month, calendar.monthrange(today.year, period_start.month)[1])
        if today < start:
            start = start.replace(year=today.year - 1)
        return start, _add_months(start, 12)

    if period_type == 'half_year':
        months_diff = (today.year - period_start.year) * 12 + (today.month - period_start.month)
        if today.day < period_start.day:
            months_diff -= 1
        periods_elapsed = max(0, months_diff // 6)
        start = _add_months(period_start, 6 * periods_elapsed)
        if today < start:
            start = _add_months(period_start, 6 * max(0, periods_elapsed - 1))
        return start, _add_months(start, 6)

    if period_type == 'custom' and period_days:
        days_since = (today - period_start).days
        if days_since < 0:
            return period_start, period_start + timedelta(days=period_days)
        n = days_since // period_days
        start = period_start + timedelta(days=period_days * n)
        return start, start + timedelta(days=period_days)

    return None, None


def get_user_display_name(user: dict) -> str:
    """Build a display name from Telegram user object."""
    first = user.get('first_name', '')
    last = user.get('last_name', '')
    username = user.get('username', '')
    full = f'{first} {last}'.strip()
    return full or username or str(user.get('id', 'Unknown'))


# ---------------------------------------------------------------------------
# Gamification — Phase 1: Core Savings Engine
# ---------------------------------------------------------------------------

def calculate_daily_surplus(budget, today: date) -> Decimal:
    """
    Sum max(daily_allowance - today_spend, 0) across all active SubBudgets
    that have a period (weekly or monthly). Falls back to total_budget / 30
    if no periodic sub-budgets exist.
    """
    from budget.models import SubBudget, Transaction

    sub_budgets = SubBudget.objects.filter(
        budget=budget,
        period_type__in=['weekly', 'monthly'],
        limit__isnull=False,
    ).prefetch_related('categories', 'tags')

    if not sub_budgets.exists():
        if budget.total_budget:
            import calendar as _cal
            days_in_month = _cal.monthrange(today.year, today.month)[1]
            daily_allowance = Decimal(str(budget.total_budget)) / days_in_month
            today_spend = Transaction.objects.filter(
                budget=budget,
                type='expense',
                created_at__date=today,
            ).aggregate(total=__import__('django.db.models', fromlist=['Sum']).Sum('amount_base'))['total'] or Decimal('0')
            return max(daily_allowance - Decimal(str(today_spend)), Decimal('0'))
        return Decimal('0')

    from django.db.models import Sum as _Sum

    total_surplus = Decimal('0')

    for sb in sub_budgets:
        period_start, period_end = get_current_period_range(
            sb.period_type, sb.period_start, sb.period_days
        )
        if period_start is None:
            continue

        days_remaining = max((period_end - today).days, 1)
        limit = Decimal(str(sb.limit))

        cat_ids = list(sb.categories.values_list('id', flat=True))
        tag_ids = list(sb.tags.values_list('id', flat=True))

        period_qs = Transaction.objects.filter(
            budget=budget,
            type='expense',
            created_at__date__gte=period_start,
            created_at__date__lt=period_end,
        )
        if cat_ids and tag_ids:
            from django.db.models import Q
            period_qs = period_qs.filter(Q(category_id__in=cat_ids) | Q(tags__id__in=tag_ids)).distinct()
        elif cat_ids:
            period_qs = period_qs.filter(category_id__in=cat_ids)
        elif tag_ids:
            period_qs = period_qs.filter(tags__id__in=tag_ids).distinct()

        spent_so_far = period_qs.aggregate(total=_Sum('amount_base'))['total'] or Decimal('0')
        spent_so_far = Decimal(str(spent_so_far))
        remaining_budget = max(limit - spent_so_far, Decimal('0'))
        daily_allowance = remaining_budget / days_remaining

        today_qs = period_qs.filter(created_at__date=today)
        today_spend = today_qs.aggregate(total=_Sum('amount_base'))['total'] or Decimal('0')
        today_spend = Decimal(str(today_spend))

        surplus = max(daily_allowance - today_spend, Decimal('0'))
        total_surplus += surplus

    return total_surplus.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def get_streak_multiplier(streak_days: int) -> Decimal:
    if streak_days >= 7:
        return Decimal('1.5')
    if streak_days >= 5:
        return Decimal('1.35')
    if streak_days >= 3:
        return Decimal('1.2')
    return Decimal('1.0')


def get_current_streak(budget) -> int:
    """
    Count consecutive days (going back from yesterday) that have a SavingsEvent.
    Today is not counted — the streak reflects completed past days.
    """
    from budget.models import SavingsEvent

    today = date.today()
    streak = 0
    check = today - timedelta(days=1)

    existing = set(
        SavingsEvent.objects.filter(budget=budget)
        .values_list('date', flat=True)
    )

    while check in existing:
        streak += 1
        check -= timedelta(days=1)

    return streak


def get_or_create_monthly_config(budget, month: str):
    """Return MonthlyConfig for the given YYYY-MM, creating with defaults if missing."""
    from budget.models import MonthlyConfig
    import random

    config, created = MonthlyConfig.objects.get_or_create(
        budget=budget,
        month=month,
        defaults={'base_split_pct': Decimal('60'), 'surprise_day': random.randint(5, 25)},
    )
    return config


def create_savings_event(budget, event_date: date) -> Optional[dict]:
    """
    Core daily function. Call once per day after spending is done.
    - Calculates surplus for event_date
    - If surplus == 0: no event created, streak implicitly breaks
    - Applies streak multiplier, splits into wish/reserve credits
    - Creates SavingsEvent and updates GoalSession.accumulated
    - Triggers completion check
    Returns the created SavingsEvent or None if no surplus / no active session.
    """
    from budget.models import GoalSession, SavingsEvent

    try:
        session = GoalSession.objects.get(budget=budget, status=GoalSession.STATUS_ACTIVE)
    except GoalSession.DoesNotExist:
        return None

    if SavingsEvent.objects.filter(budget=budget, date=event_date).exists():
        return None  # already recorded

    surplus = calculate_daily_surplus(budget, event_date)
    if surplus <= 0:
        return None  # overspend day — no event, streak broken

    month_str = event_date.strftime('%Y-%m')
    config = get_or_create_monthly_config(budget, month_str)

    streak = get_current_streak(budget)
    multiplier = get_streak_multiplier(streak)
    effective_pct = min(Decimal(str(config.base_split_pct)) * multiplier, Decimal('95'))

    wish_credit = (surplus * effective_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    reserve_credit = (surplus - wish_credit).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    is_surprise = (config.surprise_day == event_date.day)
    if is_surprise:
        wish_credit = (wish_credit * 2).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    event = SavingsEvent.objects.create(
        budget=budget,
        goal_session=session,
        date=event_date,
        daily_surplus=surplus,
        wish_split_pct=effective_pct,
        wish_credit=wish_credit,
        reserve_credit=reserve_credit,
        streak_day=streak + 1,
        multiplier=multiplier,
        is_surprise_day=is_surprise,
    )

    session.accumulated = (Decimal(str(session.accumulated)) + wish_credit).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    session.save(update_fields=['accumulated'])

    check_goal_completion(session)

    return event


def check_goal_completion(session) -> bool:
    """If accumulated >= target, mark session and wish item complete, unlock next."""
    from budget.models import WishItem

    session.refresh_from_db()
    if Decimal(str(session.accumulated)) >= Decimal(str(session.target_amount)):
        from django.utils import timezone as _tz
        session.status = session.STATUS_COMPLETED
        session.completed_at = _tz.now()
        session.save(update_fields=['status', 'completed_at'])

        session.wish_item.status = WishItem.STATUS_DONE
        session.wish_item.fulfilled_at = session.completed_at
        session.wish_item.save(update_fields=['status', 'fulfilled_at'])

        unlock_next_item(session.budget)
        return True
    return False


def unlock_next_item(budget) -> bool:
    """Activate the next locked item in queue. Returns True if one was found."""
    from budget.models import WishItem

    next_item = (
        WishItem.objects.filter(budget=budget, status=WishItem.STATUS_LOCKED)
        .order_by('queue_position')
        .first()
    )
    if next_item:
        next_item.status = WishItem.STATUS_ACTIVE
        next_item.save(update_fields=['status'])
        return True
    return False


def carry_forward_session(session) -> None:
    """On month flip: mark session carried so accumulated is preserved into next month."""
    session.status = session.STATUS_CARRIED
    session.save(update_fields=['status'])

    new_session = session.__class__.objects.create(
        budget=session.budget,
        wish_item=session.wish_item,
        target_amount=session.target_amount,
        accumulated=session.accumulated,
        status=session.__class__.STATUS_ACTIVE,
    )
    return new_session


def get_estimated_days(session) -> Optional[int]:
    """Estimate days to goal completion based on last 7 days of wish_credits."""
    from budget.models import SavingsEvent

    events = list(
        SavingsEvent.objects.filter(goal_session=session)
        .order_by('-date')[:7]
        .values_list('wish_credit', flat=True)
    )
    if not events:
        return None

    avg = sum(Decimal(str(e)) for e in events) / len(events)
    if avg <= 0:
        return None

    remaining = max(Decimal(str(session.target_amount)) - Decimal(str(session.accumulated)), Decimal('0'))
    import math
    return math.ceil(float(remaining / avg))
