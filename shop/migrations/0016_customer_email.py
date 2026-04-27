from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0015_notification_inbox_fields"),
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
    ]
