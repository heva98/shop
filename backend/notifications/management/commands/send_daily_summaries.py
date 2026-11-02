"""Send each active store's end-of-day summary: by email to its managers
and the firm's admins, and by SMS to the owner (notifications.sms_jobs).
Settings > Notifications turns each on. Run once a day after closing —
deploy/systemd/shop-daily-summary.timer does it at 21:30.

Safe to run again: anyone who already got today's summary for a store is
skipped, so a retry after a failure only sends what's missing.
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext

from core.models import Role, Store, User
from notifications.channels.email_channel import EmailChannel
from notifications.models import NotificationLog, SmsMessage
from notifications.modules import channel_enabled
from notifications.sms_jobs import daily_sales_sms_run
from reports.views import summarize_day

logger = logging.getLogger('notifications.daily_summaries')


def summary_recipients(store):
    """The store's own managers and the firm's admins — the people who act
    on the numbers. Cashiers don't get them."""
    return User.objects.filter(
        Q(store_roles__store=store, store_roles__role=Role.STORE_MANAGER)
        | Q(store_roles__store__isnull=True, store_roles__role=Role.ENTITY_ADMIN, entity=store.entity),
        is_active=True,
    ).distinct()


# The texts below are written in the recipient's language: the caller
# wraps them in translation.override(user.language). The SMS text is an
# editable template instead (notifications.sms_templates).

def long_date(day):
    """"Monday 3 November 2026", in the active language (strftime would
    always give English names)."""
    return f'{gettext(f"{day:%A}")} {day.day} {gettext(f"{day:%B}")} {day.year}'


def email_subject(store, day):
    return gettext('{store} — end of day {day}').format(store=store.name, day=f'{day:%d/%m/%Y}')


def email_text(store, day, s):
    lines = [
        gettext('{store} — end of day {day}').format(store=store.name, day=long_date(day)), '',
        gettext('Sales: TZS {total:,.0f} from {count} sale(s)').format(total=s['sales_total'], count=s['sales_count']),
        *[f'  {gettext(name)}: TZS {total:,.0f}' for name, total in s['by_method']],
        gettext('Voided sales: {n}').format(n=s['void_count']),
        gettext('Sales without an EFD receipt number: {n}').format(n=s['missing_efd']),
        gettext('Cash difference at shift close: TZS {amount:+,.0f}').format(amount=s['variance']),
        gettext('Supplier invoices received: TZS {amount:,.0f}').format(amount=s['purchases_total']),
        gettext('Products low or out of stock: {n}').format(n=s['low_stock']),
        gettext('Batches expiring within 30 days: {n}').format(n=s['expiring']),
    ]
    return '\n'.join(lines)


class Command(BaseCommand):
    help = "Send each active store's end-of-day summary: email to its managers, SMS to the owner."

    def handle(self, *args, **options):
        today = timezone.localdate()
        failures = self.send_emails(today)
        for batch in daily_sales_sms_run(today):
            failures += batch.failed_count
            for message in batch.messages.exclude(status=SmsMessage.Status.SKIPPED):
                self.stdout.write(f'SMS {message.get_status_display()} to {message.phone} for {message.store}')
            if batch.skipped_count:
                self.stdout.write(f'{batch.entity}: {batch.skipped_count} SMS skipped; see the SMS delivery log.')
        if failures:
            self.stderr.write(f'{failures} message(s) failed; see the notification and SMS delivery logs.')

    def send_emails(self, today):
        key, channel, failures = NotificationLog.Channel.EMAIL, EmailChannel(), 0
        for store in Store.objects.filter(is_active=True).select_related('entity'):
            if not channel_enabled(key, store):
                continue
            stats = summarize_day(store, today)
            for user in summary_recipients(store):
                address = user.email
                if not address:
                    continue
                already = NotificationLog.objects.filter(
                    store=store, channel=key, kind=NotificationLog.Kind.DAILY_SALES, recipient=address,
                    success=True, sent_at__date=today,
                ).exists()
                if already:
                    continue
                with translation.override(user.language or 'en'):
                    subject, body = email_subject(store, today), email_text(store, today, stats)
                success, error = True, ''
                try:
                    channel.send(address, subject, body)
                except Exception as exc:  # noqa: BLE001 — record it and carry on with the others
                    success, error = False, str(exc)[:500]
                    failures += 1
                    logger.error('Daily summary %s to %s for %s failed: %s', key, address, store.name, exc)
                NotificationLog.objects.create(
                    store=store, channel=key, kind=NotificationLog.Kind.DAILY_SALES,
                    recipient=address, success=success, error=error,
                )
                self.stdout.write(f'{"Sent" if success else "FAILED"} {key} to {address} for {store.name}')
        return failures
