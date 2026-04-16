from django.db import models
from django.utils import timezone
import secrets


class TelegramUser(models.Model):
    user_id = models.BigIntegerField(unique=True)
    first_name = models.CharField(max_length=64)
    last_name = models.CharField(max_length=64, blank=True, default='')
    username = models.CharField(max_length=64, blank=True, default='')
    photo_url = models.URLField(max_length=500, blank=True, default='')
    language_code = models.CharField(max_length=10, blank=True, default='')
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'TelegramUser({self.user_id}, {self.first_name})'


class Budget(models.Model):
    chat_id = models.BigIntegerField(unique=True)
    base_currency = models.CharField(max_length=3, default='USD')
    total_budget = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Budget(chat_id={self.chat_id}, currency={self.base_currency})'


class Category(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=64)
    icon = models.CharField(max_length=8, default='📦')
    is_default = models.BooleanField(default=False)
    created_by = models.BigIntegerField(null=True, blank=True)  # telegram user_id
    sub_budget_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = ('budget', 'name')

    def __str__(self):
        return f'{self.icon} {self.name}'


class Tag(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=64)

    class Meta:
        unique_together = ('budget', 'name')

    def __str__(self):
        return f'#{self.name}'


class Transaction(models.Model):
    INCOME = 'income'
    EXPENSE = 'expense'
    TYPE_CHOICES = [(INCOME, 'Income'), (EXPENSE, 'Expense')]

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='transactions')
    user_id = models.BigIntegerField()
    username = models.CharField(max_length=128)
    amount_original = models.DecimalField(max_digits=14, decimal_places=2)
    currency_original = models.CharField(max_length=3)
    amount_base = models.DecimalField(max_digits=14, decimal_places=2)
    type = models.CharField(max_length=7, choices=TYPE_CHOICES)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='transactions')
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.type} {self.amount_original} {self.currency_original} by {self.username}'


class UserBudgetLink(models.Model):
    """
    Links a Telegram user to a shared budget in a private-chat context.
    Created when a user accepts a budget invite.
    Overrides the default user_id-based personal budget lookup.
    """
    user_id = models.BigIntegerField(unique=True)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='members')
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'UserBudgetLink(user={self.user_id} -> budget chat_id={self.budget.chat_id})'


def _default_token():
    return secrets.token_urlsafe(24)


class BudgetInvite(models.Model):
    """
    One invite token → one shared budget.
    Multi-use: any number of users can join via the same link until it expires or is deactivated.
    """
    token = models.CharField(max_length=48, unique=True, default=_default_token)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='invites')
    created_by = models.BigIntegerField()       # telegram user_id of the creator
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'BudgetInvite(token={self.token[:8]}..., budget={self.budget_id}, active={self.is_active})'
