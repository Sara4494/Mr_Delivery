from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0014_driver_presence_real_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="idempotency_key",
            field=models.CharField(blank=True, max_length=150, null=True, verbose_name="مفتاح منع التكرار"),
        ),
        migrations.AddField(
            model_name="notification",
            name="reference_id",
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name="معرف المرجع"),
        ),
        migrations.AlterField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(
                choices=[
                    ("order_status", "Order Status"),
                    ("order_assigned", "Order Assigned"),
                    ("order_cancelled", "Order Cancelled"),
                    ("promotion", "Promotion"),
                    ("system", "System"),
                    ("chat_message", "Chat Message"),
                    ("chat", "Chat Legacy"),
                ],
                default="system",
                max_length=20,
                verbose_name="نوع الإشعار",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["employee", "-created_at"], name="shop_notif_employee_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["driver", "-created_at"], name="shop_notif_driver_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["notification_type", "-created_at"], name="shop_notif_type_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["reference_id", "notification_type"], name="shop_notif_reference_type_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["idempotency_key"], name="shop_notif_idempotency_idx"),
        ),
    ]
