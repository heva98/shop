from django.db import migrations

DEFAULTS = [
    ('Cash', 'cash', True),
    ('Mobile money', 'mobile_money', True),
    ('Bank transfer', 'bank_transfer', False),
]


def seed(apps, schema_editor):
    """A real deployment has no other way to get these rows — seed_demo
    is dev-only. Existing rows (e.g. from seed_demo) are left as they are."""
    PaymentMethod = apps.get_model('payments', 'PaymentMethod')
    for name, implementation, is_active in DEFAULTS:
        if not PaymentMethod.objects.filter(implementation=implementation).exists():
            PaymentMethod.objects.create(name=name, implementation=implementation, is_active=is_active)


class Migration(migrations.Migration):
    dependencies = [('payments', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
