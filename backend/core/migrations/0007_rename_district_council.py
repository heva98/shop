from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_user_daily_sms_time'),
    ]

    operations = [
        migrations.RenameField(model_name='entity', old_name='district', new_name='council'),
        migrations.AlterField(
            model_name='entity',
            name='council',
            field=models.CharField(blank=True, help_text='In Tanzania, a council of the region (core.tz_locations).', max_length=64),
        ),
        migrations.AlterField(
            model_name='entity',
            name='region',
            field=models.CharField(blank=True, help_text='From the list in Tanzania, else typed in.', max_length=64),
        ),
        migrations.AddField(
            model_name='entity',
            name='country',
            field=models.CharField(default='TZ', help_text='ISO code (core.countries).', max_length=2),
        ),
    ]
