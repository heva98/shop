from django.db import migrations

# Confirmed module list from architecture.txt §2.
MODULES = [
    ('category_registry', 'Product Categories', 'entity', ''),
    ('unit_of_measure', 'Unit of Measure', 'entity', ''),
    ('bundle_pricing', 'Combined/Bundle Pricing', 'entity', ''),
    ('promotions', 'Promotions', 'entity', ''),
    ('reorder_levels', 'Per-store Reorder Levels', 'store', ''),
    ('receiving_invoice', 'Receiving Invoice', 'store', ''),
    ('enquiry_broadcast', 'Enquiry — Broadcast', 'entity', 'FulfillmentStrategy'),
    ('enquiry_hub', 'Enquiry — Hub', 'entity', 'FulfillmentStrategy'),
    ('transfer', 'Transfer', 'entity', ''),
    ('pos_sale', 'POS Sale', 'store', ''),
    ('customer_credit', 'Customer Credit', 'store', ''),
    ('efd_driver', 'EFD Driver', 'store', 'FiscalDevice'),
    ('vfd_driver', 'VFD Driver', 'store', 'FiscalDevice'),
    ('cash_payment', 'Cash Payment', 'entity', 'PaymentMethod'),
    ('mobile_money_payment', 'Mobile Money Payment', 'entity', 'PaymentMethod'),
    ('bank_transfer_payment', 'Bank Transfer Payment', 'entity', 'PaymentMethod'),
    ('sms_notifier', 'SMS Notifier', 'entity', 'NotificationChannel'),
    ('email_notifier', 'Email Notifier', 'entity', 'NotificationChannel'),
    ('whatsapp_notifier', 'WhatsApp Notifier', 'entity', 'NotificationChannel'),
    ('analytics_dashboards', 'Analytics & Dashboards', 'entity', ''),
]


def seed(apps, schema_editor):
    ModuleRegistry = apps.get_model('core', 'ModuleRegistry')
    for key, name, scope, implements in MODULES:
        ModuleRegistry.objects.get_or_create(
            key=key, defaults={'name': name, 'scope': scope, 'implements': implements},
        )


def unseed(apps, schema_editor):
    ModuleRegistry = apps.get_model('core', 'ModuleRegistry')
    ModuleRegistry.objects.filter(key__in=[m[0] for m in MODULES]).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [migrations.RunPython(seed, unseed)]
