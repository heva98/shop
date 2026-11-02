from django.db import migrations

STORE_ROLES = ('cashier', 'storekeeper', 'store_manager')


def grant_store_roles(apps, schema_editor):
    """Owners registered before core.platform gave them every role get the
    store roles too, at every active store of their shop."""
    StoreRole = apps.get_model('core', 'StoreRole')
    Store = apps.get_model('core', 'Store')
    owners = (StoreRole.objects.filter(role='entity_admin', store__isnull=True, user__entity__isnull=False)
              .values_list('user_id', 'user__entity_id').distinct())
    StoreRole.objects.bulk_create(
        [StoreRole(user_id=user_id, store_id=store_id, role=role)
         for user_id, entity_id in owners
         for store_id in Store.objects.filter(entity_id=entity_id, is_active=True).values_list('id', flat=True)
         for role in STORE_ROLES],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_rename_district_council'),
    ]

    # Not reversed: the granted rows can't be told apart from ones an
    # admin gave by hand.
    operations = [
        migrations.RunPython(grant_store_roles, migrations.RunPython.noop),
    ]
