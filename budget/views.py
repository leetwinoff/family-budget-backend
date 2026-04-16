from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .models import Budget, BudgetInvite, Category, Transaction, TelegramUser, UserBudgetLink
from .serializers import (
    BudgetSerializer,
    BalanceSerializer,
    CategorySerializer,
    CategoryCreateSerializer,
    CurrencySerializer,
    SetBaseCurrencySerializer,
    TelegramUserSerializer,
    TransactionSerializer,
    TransactionCreateSerializer,
    TransactionUpdateSerializer,
)
from .services import (
    convert_amount,
    create_default_categories,
    get_chat_id,
    get_user_display_name,
    SUPPORTED_CURRENCIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_effective_chat_id(request) -> int:
    """
    Determine chat_id for the current request.
    X-Chat-Id header takes precedence — the bot embeds the group chat_id in the
    WebApp URL because Telegram omits `chat` from initData for WebApp button launches.
    Falls back to initData-based lookup (group via attachment menu, or personal budget).
    """
    header_val = request.headers.get('X-Chat-Id', '').strip()
    if header_val:
        try:
            return int(header_val)
        except ValueError:
            pass
    return get_chat_id(request.telegram_data)


def _get_budget(request) -> Budget:
    chat_id = _get_effective_chat_id(request)
    return Budget.objects.get(chat_id=chat_id)


def _period_filter(qs, period: str, date_from=None, date_to=None):
    """Apply period filter to a Transaction queryset."""
    now = timezone.now()

    if period == 'today':
        return qs.filter(created_at__date=now.date())
    if period == 'week':
        return qs.filter(created_at__gte=now - timedelta(days=7))
    if period == 'month':
        return qs.filter(created_at__year=now.year, created_at__month=now.month)
    if period == 'year':
        return qs.filter(created_at__year=now.year)
    if period == 'custom':
        filters = {}
        if date_from:
            filters['created_at__date__gte'] = date_from
        if date_to:
            filters['created_at__date__lte'] = date_to
        return qs.filter(**filters)
    # 'all' or unrecognised → no filter
    return qs


# ---------------------------------------------------------------------------
# POST /api/init
# ---------------------------------------------------------------------------

class InitView(APIView):
    """
    Initialize (or retrieve) the budget for the current chat.
    Creates default categories on first call.
    Returns budget settings + category list.
    """

    def post(self, request):
        chat_id = _get_effective_chat_id(request)
        base_currency = request.data.get('base_currency', 'USD').upper()

        budget, created = Budget.objects.get_or_create(
            chat_id=chat_id,
            defaults={'base_currency': base_currency},
        )

        if created:
            create_default_categories(budget)

        # Upsert TelegramUser from initData
        user_data = request.telegram_data.get('user', {})
        tg_user = None
        if user_data.get('id'):
            try:
                tg_user, _ = TelegramUser.objects.update_or_create(
                    user_id=user_data['id'],
                    defaults={
                        'first_name': user_data.get('first_name', ''),
                        'last_name': user_data.get('last_name', ''),
                        'username': user_data.get('username', ''),
                        'photo_url': user_data.get('photo_url', ''),
                        'language_code': user_data.get('language_code', ''),
                    },
                )
            except Exception:
                pass

        categories = budget.categories.all()
        response_data = {
            'budget': BudgetSerializer(budget).data,
            'categories': CategorySerializer(categories, many=True).data,
        }
        if tg_user:
            response_data['user'] = TelegramUserSerializer(tg_user).data
        return Response(response_data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# GET /api/balance
# ---------------------------------------------------------------------------

class BalanceView(APIView):
    """
    Returns current balance and income/expense totals for a given period.
    """

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        period = request.query_params.get('period', 'month')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')

        qs = budget.transactions.all()
        qs = _period_filter(qs, period, date_from, date_to)

        income_total = qs.filter(type=Transaction.INCOME).aggregate(
            total=Sum('amount_base')
        )['total'] or Decimal('0')

        expense_total = qs.filter(type=Transaction.EXPENSE).aggregate(
            total=Sum('amount_base')
        )['total'] or Decimal('0')

        data = {
            'balance': income_total - expense_total,
            'income_total': income_total,
            'expense_total': expense_total,
            'base_currency': budget.base_currency,
            'period': period,
        }
        return Response(BalanceSerializer(data).data)


# ---------------------------------------------------------------------------
# GET /api/transactions   POST /api/transactions
# ---------------------------------------------------------------------------

class TransactionListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        period = request.query_params.get('period', 'all')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        tx_type = request.query_params.get('type')
        category_id = request.query_params.get('category_id')

        qs = budget.transactions.select_related('category').all()
        qs = _period_filter(qs, period, date_from, date_to)

        if tx_type in (Transaction.INCOME, Transaction.EXPENSE):
            qs = qs.filter(type=tx_type)
        if category_id:
            qs = qs.filter(category_id=category_id)

        return Response(TransactionSerializer(qs, many=True).data)

    def post(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        serializer = TransactionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        # Verify category belongs to this budget
        try:
            category = budget.categories.get(pk=data['category_id'])
        except Category.DoesNotExist:
            return Response(
                {'category_id': 'Category not found in this budget.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Currency conversion
        amount_base = convert_amount(
            data['amount'],
            data['currency'],
            budget.base_currency,
        )

        user = request.telegram_data.get('user', {})
        create_kwargs = dict(
            budget=budget,
            user_id=user.get('id', 0),
            username=get_user_display_name(user),
            amount_original=data['amount'],
            currency_original=data['currency'],
            amount_base=amount_base,
            type=data['type'],
            category=category,
            comment=data.get('comment', ''),
        )
        if data.get('transaction_date'):
            create_kwargs['created_at'] = data['transaction_date']
        transaction = Transaction.objects.create(**create_kwargs)

        return Response(
            TransactionSerializer(transaction).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# DELETE /api/transactions/<id>
# ---------------------------------------------------------------------------

class TransactionDetailView(APIView):

    def patch(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            transaction = budget.transactions.select_related('category').get(pk=pk)
        except Transaction.DoesNotExist:
            return Response({'detail': 'Transaction not found.'}, status=404)

        serializer = TransactionUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        if 'category_id' in data:
            try:
                category = budget.categories.get(pk=data['category_id'])
                transaction.category = category
            except Category.DoesNotExist:
                return Response(
                    {'category_id': 'Category not found in this budget.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if 'type' in data:
            transaction.type = data['type']
        if 'comment' in data:
            transaction.comment = data['comment']
        if data.get('transaction_date'):
            transaction.created_at = data['transaction_date']

        # Recalculate amount_base if amount or currency changed
        if 'amount' in data or 'currency' in data:
            transaction.amount_original = data.get('amount', transaction.amount_original)
            transaction.currency_original = data.get('currency', transaction.currency_original)
            transaction.amount_base = convert_amount(
                transaction.amount_original,
                transaction.currency_original,
                budget.base_currency,
            )

        transaction.save()
        return Response(TransactionSerializer(transaction).data)

    def delete(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            transaction = budget.transactions.get(pk=pk)
        except Transaction.DoesNotExist:
            return Response({'detail': 'Transaction not found.'}, status=404)

        transaction.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/categories   POST /api/categories
# ---------------------------------------------------------------------------

class CategoryListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        categories = budget.categories.all()
        return Response(CategorySerializer(categories, many=True).data)

    def post(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        serializer = CategoryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = request.telegram_data.get('user', {})
        category = Category.objects.create(
            budget=budget,
            name=serializer.validated_data['name'],
            icon=serializer.validated_data.get('icon', '📦'),
            is_default=False,
            created_by=user.get('id'),
        )
        return Response(CategorySerializer(category).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# DELETE /api/categories/<id>
# ---------------------------------------------------------------------------

class CategoryDetailView(APIView):

    def delete(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            category = budget.categories.get(pk=pk)
        except Category.DoesNotExist:
            return Response({'detail': 'Category not found.'}, status=404)

        if category.is_default:
            return Response(
                {'detail': 'Default categories cannot be deleted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reassign transactions to null before deleting
        category.transactions.update(category=None)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/currencies
# ---------------------------------------------------------------------------

class CurrencyListView(APIView):
    permission_classes = []  # Public — no auth needed for currency list

    def get(self, request):
        return Response(CurrencySerializer(SUPPORTED_CURRENCIES, many=True).data)


# ---------------------------------------------------------------------------
# PUT /api/budget/currency
# ---------------------------------------------------------------------------

class BudgetCurrencyView(APIView):

    def put(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        serializer = SetBaseCurrencySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        new_currency = serializer.validated_data['currency']
        old_currency = budget.base_currency

        if new_currency == old_currency:
            return Response(BudgetSerializer(budget).data)

        # Recalculate all stored amount_base values
        transactions = budget.transactions.all()
        for tx in transactions:
            tx.amount_base = convert_amount(
                tx.amount_original,
                tx.currency_original,
                new_currency,
            )
        Transaction.objects.bulk_update(transactions, ['amount_base'])

        budget.base_currency = new_currency
        budget.save(update_fields=['base_currency'])

        return Response(BudgetSerializer(budget).data)


# ---------------------------------------------------------------------------
# Bot-internal endpoints (authenticated by X-Bot-Token header)
# ---------------------------------------------------------------------------

class _BotTokenPermission(BasePermission):
    """Allow only requests that carry the bot's own token."""
    message = 'Bot token required.'

    def has_permission(self, request, view):
        token = request.headers.get('X-Bot-Token', '')
        return bool(token and token == settings.TELEGRAM_BOT_TOKEN)


class BotInviteCreateView(APIView):
    """
    POST /api/bot/invite
    Called by the bot when a user runs /share.
    Creates (or returns an existing active) invite for that user's budget.
    Returns the full t.me deep-link the bot can send to the user.
    """
    permission_classes = [_BotTokenPermission]

    def post(self, request):
        user_id = request.data.get('user_id')
        bot_username = request.data.get('bot_username', '')

        if not user_id:
            return Response({'error': 'user_id required'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = int(user_id)

        # Resolve the budget for this user (shared or personal)
        try:
            link = UserBudgetLink.objects.select_related('budget').get(user_id=user_id)
            budget = link.budget
        except UserBudgetLink.DoesNotExist:
            budget, created = Budget.objects.get_or_create(
                chat_id=user_id,
                defaults={'base_currency': 'USD'},
            )
            if created:
                create_default_categories(budget)

        # Reuse an existing active invite if one hasn't expired yet
        existing = BudgetInvite.objects.filter(
            budget=budget,
            created_by=user_id,
            is_active=True,
            expires_at__gt=timezone.now(),
        ).first()

        if existing:
            invite = existing
        else:
            invite = BudgetInvite.objects.create(
                budget=budget,
                created_by=user_id,
                expires_at=timezone.now() + timedelta(days=7),
            )

        invite_link = f'https://t.me/{bot_username}?start=join_{invite.token}'
        return Response({'token': invite.token, 'link': invite_link})


class BotInviteJoinView(APIView):
    """
    POST /api/bot/join
    Called by the bot when a user opens a deep link: /start join_<token>
    Links the joining user to the budget the invite belongs to.
    """
    permission_classes = [_BotTokenPermission]

    def post(self, request):
        user_id = request.data.get('user_id')
        token = request.data.get('token', '')

        if not user_id or not token:
            return Response({'error': 'user_id and token required'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = int(user_id)

        try:
            invite = BudgetInvite.objects.select_related('budget').get(token=token, is_active=True)
        except BudgetInvite.DoesNotExist:
            return Response({'error': 'Invalid or expired invite link.'}, status=status.HTTP_400_BAD_REQUEST)

        if invite.expires_at < timezone.now():
            return Response({'error': 'This invite link has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        if invite.created_by == user_id:
            return Response({'error': 'already_owner'}, status=status.HTTP_400_BAD_REQUEST)

        # Link this user to the shared budget
        UserBudgetLink.objects.update_or_create(
            user_id=user_id,
            defaults={'budget': invite.budget},
        )

        return Response({
            'status': 'joined',
            'budget_chat_id': invite.budget.chat_id,
        })
