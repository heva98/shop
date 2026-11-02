"""Send each active store's end-of-day summary to its managers and the
firm's admins, by email and/or SMS (Settings > Notifications turns each
on). Run once a day after closing — deploy/systemd/shop-daily-summary.timer
does it at 21:30.

Safe to run again: anyone who already got today's summary for a store on
a channel is skipped, so a retry after a failure only sends what's missing.
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext

from core.models import ModuleEnablement, Role, Store, User
from notifications.channels.email_channel import EmailChannel
from notifications.channels.sms_channel import SMSChannel
from notifications.models import NotificationLog
from reports.views import summarize_day

logger = logging.getLogger('notifications.daily_summaries')

MODULE_KEY_BY_CHANNEL = {
    NotificationLog.Channel.EMAIL: 'email_notifier',
    NotificationLog.Channel.SMS: 'sms_notifier',
}


def channel_enabled(channel_key, store):
    return ModuleEnablement.objects.filter(
        module__key=MODULE_KEY_BY_CHANNEL[channel_key], entity=store.entity, enabled=True,
    ).filter(Q(store=store) | Q(store__isnull=True)).exists()


def summary_recipients(store):
    """The store's own managers and the firm's admins — the people who act
    on the numbers. Cashiers don't get them."""
    return User.objects.filter(
        Q(store_roles__store=store, store_roles__role=Role.STORE_MANAGER)
        | Q(store_roles__store__isnull=True, store_roles__role=Role.ENTITY_ADMIN, entity=store.entity),
        is_active=True,
    ).distinct()


# The texts below are written in the recipient's language: the caller
# wraps them in translation.override(user.language).

def sms_text(store, day, s):
    """Fits in about two SMS (≤ 306 characters) so it costs little."""
    parts = [gettext('{store} {day}: Sales TZS {total:,.0f} ({count})').format(
        store=store.name, day=f'{day:%d/%m}', total=s['sales_total'], count=s['sales_count'])]
    parts += [f'{gettext(name)} {total:,.0f}' for name, total in s['by_method']]
    if s['void_count']:
        parts.append(gettext('Voids {n}').format(n=s['void_count']))
    if s['missing_efd']:
        parts.append(gettext('NO EFD no: {n}').format(n=s['missing_efd']))
    if s['variance']:
        parts.append(gettext('Cash diff {amount:+,.0f}').format(amount=s['variance']))
    parts.append(gettext('Purchases {amount:,.0f}').format(amount=s['purchases_total']))
    parts.append(gettext('Low stock {low}, expiring 30d {expiring}').format(low=s['low_stock'], expiring=s['expiring']))
    return '. '.join(parts)[:306]


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
    help = "Send each active store's end-of-day summary to its managers by email and/or SMS."

    def handle(self, *args, **options):
        today = timezone.localdate()
        channels = {NotificationLog.Channel.EMAIL: EmailChannel(), NotificationLog.Channel.SMS: SMSChannel()}
        failures = 0
        for store in Store.objects.filter(is_active=True).select_related('entity'):
            enabled = [key for key in channels if channel_enabled(key, store)]
            if not enabled:
                continue
            stats = summarize_day(store, today)
            for key in enabled:
                channel = channels[key]
                if key == NotificationLog.Channel.SMS and not channel.configured:
                    self.stdout.write(f'{store.name}: SMS is switched on but no SMS provider is configured; skipped.')
                    continue
                for user in summary_recipients(store):
                    address = user.email if key == NotificationLog.Channel.EMAIL else user.phone
                    if not address:
                        continue
                    already = NotificationLog.objects.filter(
                        store=store, channel=key, kind=NotificationLog.Kind.DAILY_SALES, recipient=address,
                        success=True, sent_at__date=today,
                    ).exists()
                    if already:
                        continue
                    with translation.override(user.language or 'en'):
                        subject = email_subject(store, today)
                        body = (email_text(store, today, stats) if key == NotificationLog.Channel.EMAIL
                                else sms_text(store, today, stats))
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
        if failures:
            self.stderr.write(f'{failures} message(s) failed; see the notification log.')
