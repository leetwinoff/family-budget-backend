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


class SubCategory(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='sub_categories')
    parent = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='sub_categories')
    name = models.CharField(max_length=64)

    class Meta:
        unique_together = ('parent', 'name')

    def __str__(self):
        return f'{self.parent.name} → {self.name}'


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
    sub_category = models.ForeignKey(
        'SubCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='transactions')
    comment = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.type} {self.amount_original} {self.currency_original} by {self.username}'


class SubBudget(models.Model):
    PERIOD_NONE = 'none'
    PERIOD_WEEKLY = 'weekly'
    PERIOD_MONTHLY = 'monthly'
    PERIOD_HALF_YEAR = 'half_year'
    PERIOD_YEARLY = 'yearly'
    PERIOD_CUSTOM = 'custom'
    PERIOD_CHOICES = [
        (PERIOD_NONE, 'No period'),
        (PERIOD_WEEKLY, 'Weekly'),
        (PERIOD_MONTHLY, 'Monthly'),
        (PERIOD_HALF_YEAR, 'Half-year'),
        (PERIOD_YEARLY, 'Yearly'),
        (PERIOD_CUSTOM, 'Custom'),
    ]

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='sub_budgets')
    name = models.CharField(max_length=128)
    limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    categories = models.ManyToManyField(Category, blank=True, related_name='sub_budgets')
    tags = models.ManyToManyField(Tag, blank=True, related_name='sub_budgets')
    period_type = models.CharField(max_length=16, choices=PERIOD_CHOICES, default=PERIOD_NONE)
    period_start = models.DateField(null=True, blank=True)
    period_days = models.IntegerField(null=True, blank=True)  # only for period_type='custom'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'SubBudget({self.name}, budget={self.budget_id})'


class WishItem(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_FULFILLED = 'fulfilled'
    STATUS_LOCKED = 'locked'
    STATUS_DONE = 'done'
    STATUS_POOL = 'pool'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_FULFILLED, 'Fulfilled'),
        (STATUS_LOCKED, 'Locked'),
        (STATUS_DONE, 'Done (goal funded)'),
        (STATUS_POOL, 'Pool (goal-ready)'),
    ]

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='wishes')
    created_by = models.BigIntegerField()
    name = models.CharField(max_length=256)
    description = models.TextField(blank=True, default='')
    link = models.URLField(max_length=2000, blank=True, default='')
    price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True, default='')
    image_url = models.TextField(blank=True, default='')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    sort_order = models.IntegerField(default=0)
    queue_position = models.IntegerField(null=True, blank=True)
    goal_ready = models.BooleanField(default=False)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', '-created_at']

    def __str__(self):
        return f'WishItem({self.name}, by={self.created_by})'


class GoalSession(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_COMPLETED = 'completed'
    STATUS_CARRIED = 'carried'
    STATUS_ABANDONED = 'abandoned'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CARRIED, 'Carried forward'),
        (STATUS_ABANDONED, 'Abandoned'),
    ]

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='goal_sessions')
    wish_item = models.ForeignKey(WishItem, on_delete=models.CASCADE, related_name='goal_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    target_amount = models.DecimalField(max_digits=14, decimal_places=2)
    accumulated = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'GoalSession({self.wish_item.name}, {self.status}, {self.accumulated}/{self.target_amount})'


class SavingsEvent(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='savings_events')
    goal_session = models.ForeignKey(GoalSession, on_delete=models.CASCADE, related_name='savings_events')
    date = models.DateField()
    daily_surplus = models.DecimalField(max_digits=14, decimal_places=2)
    wish_split_pct = models.DecimalField(max_digits=5, decimal_places=2)
    wish_credit = models.DecimalField(max_digits=14, decimal_places=2)
    reserve_credit = models.DecimalField(max_digits=14, decimal_places=2)
    streak_day = models.IntegerField(default=0)
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    is_surprise_day = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('budget', 'date')

    def __str__(self):
        return f'SavingsEvent({self.date}, credit={self.wish_credit})'


class MonthlyConfig(models.Model):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='monthly_configs')
    month = models.CharField(max_length=7)  # YYYY-MM
    base_split_pct = models.DecimalField(max_digits=5, decimal_places=2, default=60)
    surprise_day = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('budget', 'month')

    def __str__(self):
        return f'MonthlyConfig({self.budget_id}, {self.month}, split={self.base_split_pct}%)'


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
