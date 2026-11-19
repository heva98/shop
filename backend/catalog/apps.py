from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = 'catalog'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .models import CatalogRevision, Category, GenericDrug, Product, UnitOfMeasure

        def changed(sender, instance, raw=False, **kwargs):
            # raw: loading a fixture, where the entity may not exist yet.
            if not raw:
                CatalogRevision.bump(instance.entity_id)

        # Deleting a category or generic medicine clears it from products
        # with an SQL UPDATE that sends no signal; its own delete bumps.
        for model in (Product, Category, UnitOfMeasure, GenericDrug):
            post_save.connect(changed, sender=model, weak=False, dispatch_uid=f'catalog-revision-save-{model.__name__}')
            post_delete.connect(changed, sender=model, weak=False, dispatch_uid=f'catalog-revision-delete-{model.__name__}')
