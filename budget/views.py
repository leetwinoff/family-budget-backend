from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum, Q
from django.utils import timezone
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .models import Budget, BudgetInvite, Category, SubBudget, SubCategory, Tag, Transaction, TelegramUser, UserBudgetLink
from .serializers import (
    BudgetSerializer,
    BalanceSerializer,
    CategorySerializer,
    CategoryCreateSerializer,
    CurrencySerializer,
    SetBaseCurrencySerializer,
    SetTotalBudgetSerializer,
    SubBudgetSerializer,
    SubBudgetCreateSerializer,
    SubCategorySerializer,
    SubCategoryCreateSerializer,
    TagSerializer,
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
    return qs


# ---------------------------------------------------------------------------
# POST /api/init
# ---------------------------------------------------------------------------

class InitView(APIView):
    def post(self, request):
        chat_id = _get_effective_chat_id(request)
        base_currency = request.data.get('base_currency', 'USD').upper()

        budget, created = Budget.objects.get_or_create(
            chat_id=chat_id,
            defaults={'base_currency': base_currency},
        )

        if created:
            create_default_categories(budget)

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

        total_budget = budget.total_budget
        remaining = (total_budget - expense_total) if total_budget is not None else None

        data = {
            'balance': income_total - expense_total,
            'income_total': income_total,
            'expense_total': expense_total,
            'base_currency': budget.base_currency,
            'period': period,
            'total_budget': total_budget,
            'remaining': remaining,
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
        user_id = request.query_params.get('user_id')
        tag_ids_raw = request.query_params.get('tag_ids')

        qs = budget.transactions.select_related('category').prefetch_related('tags').all()
        qs = _period_filter(qs, period, date_from, date_to)

        if tx_type in (Transaction.INCOME, Transaction.EXPENSE):
            qs = qs.filter(type=tx_type)
        if category_id:
            qs = qs.filter(category_id=category_id)
        if user_id:
            try:
                qs = qs.filter(user_id=int(user_id))
            except ValueError:
                pass
        if tag_ids_raw:
            try:
                tag_ids = [int(t) for t in tag_ids_raw.split(',') if t.strip()]
                for tid in tag_ids:
                    qs = qs.filter(tags__id=tid)
            except ValueError:
                pass

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

        # Category is optional
        category = None
        if data.get('category_id'):
            try:
                category = budget.categories.get(pk=data['category_id'])
            except Category.DoesNotExist:
                return Response(
                    {'category_id': 'Category not found in this budget.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Sub-category is optional; its parent category is implied
        sub_category = None
        sub_category_id = data['sub_category_id'] if isinstance(data, dict) else None
        if sub_category_id:
            try:
                sub_category = SubCategory.objects.get(pk=int(sub_category_id), budget=budget)
                if category is None:
                    category = sub_category.parent
            except SubCategory.DoesNotExist:
                return Response(
                    {'sub_category_id': 'Sub-category not found in this budget.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

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
            sub_category=sub_category,
            comment=data.get('comment', ''),
        )
        if data.get('transaction_date'):
            create_kwargs['created_at'] = data['transaction_date']
        transaction = Transaction.objects.create(**create_kwargs)

        # Assign tags
        tag_ids = data.get('tag_ids', [])
        if tag_ids:
            tags = budget.tags.filter(pk__in=tag_ids)
            transaction.tags.set(tags)

        return Response(
            TransactionSerializer(transaction).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# PATCH/DELETE /api/transactions/<id>
# ---------------------------------------------------------------------------

class TransactionDetailView(APIView):

    def patch(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            transaction = budget.transactions.select_related('category', 'sub_category').prefetch_related('tags').get(pk=pk)
        except Transaction.DoesNotExist:
            return Response({'detail': 'Transaction not found.'}, status=404)

        serializer = TransactionUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data: dict = serializer.validated_data  # type: ignore[assignment]

        if 'category_id' in data:
            if data['category_id'] is None:
                transaction.category = None
            else:
                try:
                    category = budget.categories.get(pk=data['category_id'])
                    transaction.category = category
                except Category.DoesNotExist:
                    return Response(
                        {'category_id': 'Category not found in this budget.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        if 'sub_category_id' in data:
            sc_id = data.get('sub_category_id')
            if sc_id is None:
                transaction.sub_category = None
            else:
                try:
                    sc = SubCategory.objects.get(pk=int(sc_id), budget=budget)
                    transaction.sub_category = sc
                    if transaction.category is None:
                        transaction.category = sc.parent
                except SubCategory.DoesNotExist:
                    return Response(
                        {'sub_category_id': 'Sub-category not found in this budget.'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        if 'tag_ids' in data:
            tags = budget.tags.filter(pk__in=data['tag_ids'])
            transaction.tags.set(tags)

        if 'type' in data:
            transaction.type = data['type']
        if 'comment' in data:
            transaction.comment = data['comment']
        if data.get('transaction_date'):
            transaction.created_at = data['transaction_date']

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
# GET/POST /api/categories
# ---------------------------------------------------------------------------

class CategoryListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        period = request.query_params.get('period', 'month')
        categories = budget.categories.all()
        return Response(CategorySerializer(categories, many=True, context={'period': period}).data)

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
        return Response(CategorySerializer(category, context={'period': 'month'}).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# DELETE /api/categories/<id>   PATCH /api/categories/<id>
# ---------------------------------------------------------------------------

class CategoryDetailView(APIView):

    def patch(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            category = budget.categories.get(pk=pk)
        except Category.DoesNotExist:
            return Response({'detail': 'Category not found.'}, status=404)

        serializer = SetCategoryLimitSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        category.sub_budget_limit = serializer.validated_data['sub_budget_limit']
        category.save(update_fields=['sub_budget_limit'])

        period = request.query_params.get('period', 'month')
        return Response(CategorySerializer(category, context={'period': period}).data)

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

        category.transactions.update(category=None)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/currencies
# ---------------------------------------------------------------------------

class CurrencyListView(APIView):
    permission_classes = []

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
# PUT /api/budget/total  — set/clear total budget ceiling
# ---------------------------------------------------------------------------

class BudgetTotalView(APIView):

    def put(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found. Call /api/init first.'}, status=404)

        serializer = SetTotalBudgetSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        budget.total_budget = serializer.validated_data['total_budget']
        budget.save(update_fields=['total_budget'])
        return Response(BudgetSerializer(budget).data)


# ---------------------------------------------------------------------------
# GET/POST /api/tags   DELETE /api/tags/<id>
# ---------------------------------------------------------------------------

class TagListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        tags = budget.tags.all().order_by('name')
        return Response(TagSerializer(tags, many=True).data)

    def post(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        name = request.data.get('name', '').strip().lstrip('#')
        if not name:
            return Response({'name': 'Tag name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        tag, created = Tag.objects.get_or_create(budget=budget, name=name)
        return Response(TagSerializer(tag).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TagDetailView(APIView):

    def delete(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            tag = budget.tags.get(pk=pk)
        except Tag.DoesNotExist:
            return Response({'detail': 'Tag not found.'}, status=404)

        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/budget/members
# ---------------------------------------------------------------------------

class BudgetMembersView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        # Collect distinct user_ids from transactions
        user_rows = (
            budget.transactions
            .values('user_id', 'username')
            .distinct()
            .order_by('username')
        )

        user_ids = [r['user_id'] for r in user_rows]
        photo_map = {
            u.user_id: u.photo_url
            for u in TelegramUser.objects.filter(user_id__in=user_ids)
        }
        members = [
            {
                'user_id': r['user_id'],
                'username': r['username'],
                'photo_url': photo_map.get(r['user_id'], ''),
            }
            for r in user_rows
        ]
        return Response(members)


# ---------------------------------------------------------------------------
# GET/POST /api/sub-budgets   DELETE /api/sub-budgets/<id>
# ---------------------------------------------------------------------------

class SubBudgetListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        period = request.query_params.get('period', 'month')
        sub_budgets = budget.sub_budgets.prefetch_related('categories', 'tags').all()
        return Response(SubBudgetSerializer(sub_budgets, many=True, context={'period': period}).data)

    def post(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        serializer = SubBudgetCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        sub_budget = SubBudget.objects.create(
            budget=budget,
            name=data['name'],
            limit=data.get('limit'),
        )

        if data.get('category_ids'):
            cats = budget.categories.filter(pk__in=data['category_ids'])
            sub_budget.categories.set(cats)

        if data.get('tag_ids'):
            tags = budget.tags.filter(pk__in=data['tag_ids'])
            sub_budget.tags.set(tags)

        return Response(
            SubBudgetSerializer(sub_budget, context={'period': 'month'}).data,
            status=status.HTTP_201_CREATED,
        )


class SubBudgetDetailView(APIView):

    def patch(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            sub_budget = budget.sub_budgets.get(pk=pk)
        except SubBudget.DoesNotExist:
            return Response({'detail': 'Sub-budget not found.'}, status=404)

        serializer = SubBudgetCreateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data
        if 'name' in data:
            sub_budget.name = data['name']
        if 'limit' in request.data:
            sub_budget.limit = data.get('limit')
        sub_budget.save()

        if 'category_ids' in data:
            cats = Category.objects.filter(budget=budget, id__in=data['category_ids'])
            sub_budget.categories.set(cats)

        if 'tag_ids' in data:
            tags = Tag.objects.filter(budget=budget, id__in=data['tag_ids'])
            sub_budget.tags.set(tags)

        period = request.query_params.get('period', 'month')
        return Response(
            SubBudgetSerializer(sub_budget, context={'period': period}).data,
            status=200,
        )

    def delete(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            sub_budget = budget.sub_budgets.get(pk=pk)
        except SubBudget.DoesNotExist:
            return Response({'detail': 'Sub-budget not found.'}, status=404)

        sub_budget.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET/POST /api/sub-categories   DELETE /api/sub-categories/<id>
# ---------------------------------------------------------------------------

class SubCategoryListView(APIView):

    def get(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        sub_categories = SubCategory.objects.filter(budget=budget).select_related('parent').order_by('parent__name', 'name')
        return Response(SubCategorySerializer(sub_categories, many=True).data)

    def post(self, request):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        serializer = SubCategoryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data: dict = serializer.validated_data  # type: ignore[assignment]

        try:
            parent = Category.objects.get(pk=data['parent_id'], budget=budget)
        except Category.DoesNotExist:
            return Response({'parent_id': 'Category not found in this budget.'}, status=status.HTTP_400_BAD_REQUEST)

        sub_cat, created = SubCategory.objects.get_or_create(
            budget=budget,
            parent=parent,
            name=data['name'],
        )
        return Response(
            SubCategorySerializer(sub_cat).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class SubCategoryDetailView(APIView):

    def delete(self, request, pk):
        try:
            budget = _get_budget(request)
        except Budget.DoesNotExist:
            return Response({'detail': 'Budget not found.'}, status=404)

        try:
            sub_cat = SubCategory.objects.get(pk=pk, budget=budget)
        except SubCategory.DoesNotExist:
            return Response({'detail': 'Sub-category not found.'}, status=404)

        sub_cat.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Bot-internal endpoints (authenticated by X-Bot-Token header)
# ---------------------------------------------------------------------------

class _BotTokenPermission(BasePermission):
    message = 'Bot token required.'

    def has_permission(self, request, view):
        token = request.headers.get('X-Bot-Token', '')
        return bool(token and token == settings.TELEGRAM_BOT_TOKEN)


class BotInviteCreateView(APIView):
    permission_classes = [_BotTokenPermission]

    def post(self, request):
        user_id = request.data.get('user_id')
        bot_username = request.data.get('bot_username', '')

        if not user_id:
            return Response({'error': 'user_id required'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = int(user_id)

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

        UserBudgetLink.objects.update_or_create(
            user_id=user_id,
            defaults={'budget': invite.budget},
        )

        return Response({
            'status': 'joined',
            'budget_chat_id': invite.budget.chat_id,
        })
