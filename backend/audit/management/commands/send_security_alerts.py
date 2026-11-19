"""Texts (and emails) shop owners about new security events — see
audit.alerts. deploy/systemd/shop-security-alerts.timer runs it every 5
minutes; each alert is sent once, so running it again is safe."""

from django.core.management.base import BaseCommand

from audit import alerts
from core.jobs import JobAlreadyRunning, single_flight


class Command(BaseCommand):
    help = 'Send new security alerts to shop owners (and blocked addresses to ADMINS).'

    def handle(self, *args, **options):
        try:
            with single_flight('security-alerts', minutes=10):
                result = alerts.run()
        except JobAlreadyRunning:
            self.stdout.write('Another copy is already sending alerts.')
            return
        self.stdout.write(f"{result['alerts']} new alert(s), {result['messages']} message(s) sent.")
