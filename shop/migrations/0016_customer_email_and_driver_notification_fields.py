from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0013_chatmessage_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="customer",
            name="email",
            field=models.EmailField(
                blank=True,
                max_length=254,
                null=True,
                unique=True,
                verbose_name="البريد الإلكتروني",
            ),
        ),
        migrations.AddIndex(
            model_name="customer",
            index=models.Index(fields=["email"], name="shop_custom_email_4fb6d5_idx"),
        ),
        migrations.AddField(
            model_name="notification",
            name="image_url",
            field=models.TextField(blank=True, null=True, verbose_name="Image URL"),
        ),
        migrations.AddField(
            model_name="notification",
            name="order_id",
            field=models.PositiveBigIntegerField(blank=True, null=True, verbose_name="Order ID"),
        ),
        migrations.AddField(
            model_name="notification",
            name="store_id",
            field=models.PositiveBigIntegerField(blank=True, null=True, verbose_name="Store ID"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["driver", "order_id"], name="shop_notif_drv_order_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["driver", "store_id"], name="shop_notif_drv_store_idx"),
        ),
    ]
