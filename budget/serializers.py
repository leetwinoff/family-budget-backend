from decimal import Decimal

from rest_framework import serializers

from .models import Budget, Category, SubBudget, SubCategory, Tag, Transaction, TelegramUser, WishItem
from .services import SUPPORTED_CURRENCY_CODES


class TelegramUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramUser
        fields = ['user_id', 'first_name', 'last_name', 'username', 'photo_url']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name']


class SubCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCategory
        fields = ['id', 'name', 'parent']


class SubCategoryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=64)
    parent_id = serializers.IntegerField()

    def validate_name(self, value):
        return value.strip()


class CategorySerializer(serializers.ModelSerializer):
    spent = serializers.SerializerMethodField()
    sub_categories = SubCategorySerializer(many=True, read_only=True)

    class Meta:
        model = Category
        fields = ['id', 'name', 'icon', 'is_default', 'spent', 'sub_categories']

    def get_spent(self, obj):
        period = self.context.get('period', 'month')
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum

        qs = obj.transactions.filter(type=Transaction.EXPENSE)
        now = timezone.now()
        if period == 'today':
            qs = qs.filter(created_at__date=now.date())
        elif period == 'week':
            qs = qs.filter(created_at__gte=now - timedelta(days=7))
        elif period == 'month':
            qs = qs.filter(created_at__year=now.year, created_at__month=now.month)
        elif period == 'year':
            qs = qs.filter(created_at__year=now.year)

        result = qs.aggregate(total=Sum('amount_base'))['total']
        return str(result or Decimal('0'))


class CategoryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['name', 'icon']

    def validate_name(self, value):
        return value.strip()

    def validate_icon(self, value):
        return value.strip() or '📦'


class TransactionSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    sub_category = SubCategorySerializer(read_only=True)
    tags = TagSerializer(many=True, read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id',
            'user_id',
            'username',
            'amount_original',
            'currency_original',
            'amount_base',
            'type',
            'category',
            'sub_category',
            'tags',
            'comment',
            'created_at',
        ]


class TransactionCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(max_length=3)
    type = serializers.ChoiceField(choices=[Transaction.INCOME, Transaction.EXPENSE])
    category_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    sub_category_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    transaction_date = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_currency(self, value):
        value = value.upper()
        if value not in SUPPORTED_CURRENCY_CODES:
            raise serializers.ValidationError(f'Unsupported currency: {value}')
        return value


class BudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Budget
        fields = ['chat_id', 'base_currency', 'total_budget', 'created_at']


class BalanceSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    income_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    expense_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    base_currency = serializers.CharField()
    period = serializers.CharField()
    total_budget = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)
    remaining = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True)


class CurrencySerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    symbol = serializers.CharField()


class TransactionUpdateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'), required=False)
    currency = serializers.CharField(max_length=3, required=False)
    type = serializers.ChoiceField(choices=[Transaction.INCOME, Transaction.EXPENSE], required=False)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    sub_category_id = serializers.IntegerField(required=False, allow_null=True)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)
    transaction_date = serializers.DateTimeField(required=False, allow_null=True)

    def validate_currency(self, value):
        value = value.upper()
        if value not in SUPPORTED_CURRENCY_CODES:
            raise serializers.ValidationError(f'Unsupported currency: {value}')
        return value


class SetBaseCurrencySerializer(serializers.Serializer):
    currency = serializers.CharField(max_length=3)

    def validate_currency(self, value):
        value = value.upper()
        if value not in SUPPORTED_CURRENCY_CODES:
            raise serializers.ValidationError(f'Unsupported currency: {value}')
        return value


class SetTotalBudgetSerializer(serializers.Serializer):
    total_budget = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), allow_null=True)



class SubBudgetSerializer(serializers.ModelSerializer):
    category_ids = serializers.SerializerMethodField()
    tag_ids = serializers.SerializerMethodField()
    spent = serializers.SerializerMethodField()

    class Meta:
        model = SubBudget
        fields = [
            'id', 'name', 'limit', 'category_ids', 'tag_ids', 'spent',
            'period_type', 'period_start', 'period_days',
        ]

    def get_category_ids(self, obj):
        return list(obj.categories.values_list('id', flat=True))

    def get_tag_ids(self, obj):
        return list(obj.tags.values_list('id', flat=True))

    def get_spent(self, obj):
        from django.db.models import Q, Sum
        from django.utils import timezone
        from datetime import timedelta
        from .services import get_current_period_range

        qs = obj.budget.transactions.filter(type=Transaction.EXPENSE)

        if obj.period_type != 'none' and obj.period_start:
            start, end = get_current_period_range(obj.period_type, obj.period_start, obj.period_days)
            if start and end:
                qs = qs.filter(created_at__date__gte=start, created_at__date__lt=end)
        else:
            period = self.context.get('period', 'month')
            now = timezone.now()
            if period == 'today':
                qs = qs.filter(created_at__date=now.date())
            elif period == 'week':
                qs = qs.filter(created_at__gte=now - timedelta(days=7))
            elif period == 'month':
                qs = qs.filter(created_at__year=now.year, created_at__month=now.month)
            elif period == 'year':
                qs = qs.filter(created_at__year=now.year)

        cat_ids = list(obj.categories.values_list('id', flat=True))
        tag_ids = list(obj.tags.values_list('id', flat=True))

        if not cat_ids and not tag_ids:
            return str(Decimal('0'))

        qs = qs.filter(
            Q(category_id__in=cat_ids) | Q(tags__id__in=tag_ids)
        ).distinct()

        result = qs.aggregate(total=Sum('amount_base'))['total']
        return str(result or Decimal('0'))


class SubBudgetCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    limit = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0'), allow_null=True, required=False)
    category_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    tag_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    period_type = serializers.ChoiceField(
        choices=['none', 'weekly', 'monthly', 'half_year', 'yearly', 'custom'],
        required=False,
        default='none',
    )
    period_start = serializers.DateField(required=False, allow_null=True, default=None)
    period_days = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)

    def validate_name(self, value):
        return value.strip()


class WishItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = WishItem
        fields = [
            'id', 'created_by', 'title', 'description', 'link',
            'price', 'currency', 'image_url',
            'is_reserved', 'reserved_by', 'is_fulfilled', 'created_at',
        ]


class WishItemCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=256)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True, default='')
    link = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    price = serializers.DecimalField(max_digits=14, decimal_places=2, allow_null=True, required=False, default=None)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default='')
    image_url = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')

    def validate_title(self, value):
        return value.strip()
