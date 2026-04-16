from decimal import Decimal

from rest_framework import serializers

from .models import Budget, Category, Transaction, TelegramUser
from .services import SUPPORTED_CURRENCY_CODES


class TelegramUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramUser
        fields = ['user_id', 'first_name', 'last_name', 'username', 'photo_url']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'icon', 'is_default']


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
            'comment',
            'created_at',
        ]


class TransactionCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'))
    currency = serializers.CharField(max_length=3)
    type = serializers.ChoiceField(choices=[Transaction.INCOME, Transaction.EXPENSE])
    category_id = serializers.IntegerField()
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    transaction_date = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_currency(self, value):
        value = value.upper()
        if value not in SUPPORTED_CURRENCY_CODES:
            raise serializers.ValidationError(f'Unsupported currency: {value}')
        return value

    def validate_category_id(self, value):
        # Budget-scoped validation happens in the view
        return value


class BudgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Budget
        fields = ['chat_id', 'base_currency', 'created_at']


class BalanceSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    income_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    expense_total = serializers.DecimalField(max_digits=14, decimal_places=2)
    base_currency = serializers.CharField()
    period = serializers.CharField()


class CurrencySerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    symbol = serializers.CharField()


class TransactionUpdateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal('0.01'), required=False)
    currency = serializers.CharField(max_length=3, required=False)
    type = serializers.ChoiceField(choices=[Transaction.INCOME, Transaction.EXPENSE], required=False)
    category_id = serializers.IntegerField(required=False)
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
