from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0010_wishitem_goal_ready_wishitem_queue_position_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="wishitem",
            name="fulfilled_by",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="wishitem",
            name="self_fulfilled",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
