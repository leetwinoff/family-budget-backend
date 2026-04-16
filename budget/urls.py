from django.urls import path
from . import views

urlpatterns = [
    path('init',                   views.InitView.as_view(),             name='init'),
    path('balance',                views.BalanceView.as_view(),          name='balance'),
    path('transactions',           views.TransactionListView.as_view(),  name='transactions'),
    path('transactions/<int:pk>',  views.TransactionDetailView.as_view(),name='transaction-detail'),
    path('categories',             views.CategoryListView.as_view(),     name='categories'),
    path('categories/<int:pk>',    views.CategoryDetailView.as_view(),   name='category-detail'),
    path('currencies',             views.CurrencyListView.as_view(),     name='currencies'),
    path('budget/currency',        views.BudgetCurrencyView.as_view(),   name='budget-currency'),
    path('budget/total',           views.BudgetTotalView.as_view(),      name='budget-total'),
    path('budget/members',         views.BudgetMembersView.as_view(),    name='budget-members'),
    path('tags',                   views.TagListView.as_view(),          name='tags'),
    path('tags/<int:pk>',          views.TagDetailView.as_view(),        name='tag-detail'),
    # Bot-internal endpoints (X-Bot-Token auth)
    path('bot/invite',             views.BotInviteCreateView.as_view(),  name='bot-invite'),
    path('bot/join',               views.BotInviteJoinView.as_view(),    name='bot-join'),
]
