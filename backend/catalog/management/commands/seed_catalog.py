"""Seeds the standard starter catalog for one real shop (Entity).

Unlike core.management.commands.seed_demo (which also fabricates a demo
Entity and demo Users — dev/demo-only, never for a real deployment), this
command touches only catalog.{Category,UnitOfMeasure,Product} for an
Entity you already created yourself (via the Django admin or the app's
own Admin screens). Safe to run in production, and safe to re-run
(idempotent).

    python manage.py seed_catalog --entity "Your Shop Name"
    python manage.py seed_catalog --entity-id 5ff8dc2b-f079-46d2-824c-841462eda8d1
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.seed_data import seed_catalog
from core.models import Entity


class Command(BaseCommand):
    help = "Seed the standard starter catalog for one Entity (idempotent)."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--entity', help='Exact Entity.name to seed the catalog for.')
        group.add_argument('--entity-id', help='Entity.id (UUID) to seed the catalog for.')

    @transaction.atomic
    def handle(self, *args, **options):
        entity = self._resolve_entity(options)
        products = seed_catalog(entity)
        self.stdout.write(self.style.SUCCESS(
            f'Seeded catalog for "{entity.name}": {len(products)} products.',
        ))

    def _resolve_entity(self, options):
        if options.get('entity_id'):
            try:
                return Entity.objects.get(id=options['entity_id'])
            except Entity.DoesNotExist as exc:
                raise CommandError(f"No entity with id {options['entity_id']!r}.") from exc
        name = options['entity']
        matches = list(Entity.objects.filter(name=name))
        if not matches:
            raise CommandError(
                f'No entity named {name!r}. Create it first (Django admin, or '
                'the app\'s own onboarding flow), then re-run this command.',
            )
        if len(matches) > 1:
            raise CommandError(
                f'{len(matches)} entities are named {name!r} — use --entity-id instead. '
                f'Ids: {", ".join(str(e.id) for e in matches)}',
            )
        return matches[0]
