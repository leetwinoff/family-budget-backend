from django.urls import path
from . import views

urlpatterns = [
    path('init',                      views.InitView.as_view(),             name='init'),
    path('balance',                   views.BalanceView.as_view(),          name='balance'),
    path('transactions',              views.TransactionListView.as_view(),  name='transactions'),
    path('transactions/<int:pk>',     views.TransactionDetailView.as_view(),name='transaction-detail'),
    path('categories',                views.CategoryListView.as_view(),     name='categories'),
    path('categories/<int:pk>',       views.CategoryDetailView.as_view(),   name='category-detail'),
    path('currencies',                views.CurrencyListView.as_view(),     name='currencies'),
    path('budget/currency',           views.BudgetCurrencyView.as_view(),   name='budget-currency'),
    path('budget/total',              views.BudgetTotalView.as_view(),      name='budget-total'),
    path('budget/members',            views.BudgetMembersView.as_view(),    name='budget-members'),
    path('tags',                      views.TagListView.as_view(),          name='tags'),
    path('tags/<int:pk>',             views.TagDetailView.as_view(),        name='tag-detail'),
    path('sub-budgets',               views.SubBudgetListView.as_view(),    name='sub-budgets'),
    path('sub-budgets/<int:pk>',      views.SubBudgetDetailView.as_view(),  name='sub-budget-detail'),
    path('sub-categories',            views.SubCategoryListView.as_view(),  name='sub-categories'),
    path('sub-categories/<int:pk>',   views.SubCategoryDetailView.as_view(), name='sub-category-detail'),
    # Wishlist
    path('wishes',                   views.WishListView.as_view(),          name='wishes'),
    path('wishes/<int:pk>',          views.WishDetailView.as_view(),        name='wish-detail'),
    path('wishes/<int:pk>/fulfill',  views.WishFulfillView.as_view(),       name='wish-fulfill'),
    # Bot-internal endpoints (X-Bot-Token auth)
    path('bot/invite',                views.BotInviteCreateView.as_view(),  name='bot-invite'),
    path('bot/join',                  views.BotInviteJoinView.as_view(),    name='bot-join'),
    path('bot/wish',                  views.BotAddWishView.as_view(),       name='bot-wish'),
    # Goal engine (Phase 1)
    path('goal/status',               views.GoalStatusView.as_view(),            name='goal-status'),
    path('goal/sessions',             views.GoalSessionListView.as_view(),        name='goal-sessions'),
    path('goal/sessions/<int:pk>/abandon', views.GoalSessionAbandonView.as_view(), name='goal-session-abandon'),
    path('goal/carry-forward',        views.GoalCarryForwardView.as_view(),       name='goal-carry-forward'),
    path('goal/events',               views.SavingsEventListView.as_view(),       name='goal-events'),
    path('goal/config',               views.GoalConfigView.as_view(),             name='goal-config'),
]
