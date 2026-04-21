from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0013_chatmessage_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='driver',
            name='is_online',
            field=models.BooleanField(default=False, verbose_name='متصل الآن'),
        ),
        migrations.AddField(
            model_name='driverpresenceconnection',
            name='last_heartbeat_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='آخر heartbeat'),
        ),
        migrations.AddIndex(
            model_name='driverpresenceconnection',
            index=models.Index(fields=['driver', '-last_heartbeat_at'], name='drvprs_driver_heartbeat_idx'),
        ),
    ]
