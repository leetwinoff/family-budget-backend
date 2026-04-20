from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0008_wish_item'),
    ]

    operations = [
        migrations.RenameField(
            model_name='wishitem',
            old_name='title',
            new_name='name',
        ),
        migrations.RemoveField(
            model_name='wishitem',
            name='is_reserved',
        ),
        migrations.RemoveField(
            model_name='wishitem',
            name='reserved_by',
        ),
        migrations.RemoveField(
            model_name='wishitem',
            name='is_fulfilled',
        ),
        migrations.AddField(
            model_name='wishitem',
            name='status',
            field=models.CharField(
                choices=[('active', 'Active'), ('fulfilled', 'Fulfilled')],
                default='active',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='wishitem',
            name='fulfilled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='wishitem',
            name='sort_order',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wishitem',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name='wishitem',
            name='image_url',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterModelOptions(
            name='wishitem',
            options={'ordering': ['sort_order', '-created_at']},
        ),
    ]
