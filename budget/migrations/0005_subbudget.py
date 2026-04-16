from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0004_add_budget_total_category_limit_tags"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubBudget",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=128)),
                (
                    "limit",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=14, null=True
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "budget",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sub_budgets",
                        to="budget.budget",
                    ),
                ),
                (
                    "categories",
                    models.ManyToManyField(
                        blank=True,
                        related_name="sub_budgets",
                        to="budget.category",
                    ),
                ),
                (
                    "tags",
                    models.ManyToManyField(
                        blank=True,
                        related_name="sub_budgets",
                        to="budget.tag",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
    ]
