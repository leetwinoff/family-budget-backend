from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0006_subcategory_transaction_sub_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='subbudget',
            name='period_type',
            field=models.CharField(
                choices=[
                    ('none', 'No period'),
                    ('weekly', 'Weekly'),
                    ('monthly', 'Monthly'),
                    ('half_year', 'Half-year'),
                    ('yearly', 'Yearly'),
                    ('custom', 'Custom'),
                ],
                default='none',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='subbudget',
            name='period_start',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subbudget',
            name='period_days',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
