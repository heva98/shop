"""Load the shipped SMS texts (notifications.sms_templates.DEFAULT_TEMPLATES)
for every shop. Missing ones are added; --force also resets edited ones."""

from django.core.management.base import BaseCommand

from core.models import Entity
from notifications.sms_service import ensure_templates


class Command(BaseCommand):
    help = 'Create the default SMS templates for every shop (--force resets edited ones).'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='Reset edited templates to the defaults.')

    def handle(self, *args, force=False, **options):
        count = 0
        for entity in Entity.objects.all():
            ensure_templates(entity, force=force)
            count += 1
        self.stdout.write(f'SMS templates {"reset" if force else "checked"} for {count} shop(s).')
