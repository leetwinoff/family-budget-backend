from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import budget.models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0002_telegramuser_alter_transaction_created_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserBudgetLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.BigIntegerField(unique=True)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('budget', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='budget.budget')),
            ],
        ),
        migrations.CreateModel(
            name='BudgetInvite',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(default=budget.models._default_token, max_length=48, unique=True)),
                ('created_by', models.BigIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('is_active', models.BooleanField(default=True)),
                ('budget', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invites', to='budget.budget')),
            ],
        ),
    ]
