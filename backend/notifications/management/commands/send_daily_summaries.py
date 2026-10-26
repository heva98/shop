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
from django.utils import timezone

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


def sms_text(store, day, s):
    """Fits in about two SMS (≤ 306 characters) so it costs little."""
    parts = [f'{store.name} {day:%d/%m}: Sales TZS {s["sales_total"]:,.0f} ({s["sales_count"]})']
    parts += [f'{name} {total:,.0f}' for name, total in s['by_method']]
    if s['void_count']:
        parts.append(f'Voids {s["void_count"]}')
    if s['missing_efd']:
        parts.append(f'NO EFD no: {s["missing_efd"]}')
    if s['variance']:
        parts.append(f'Cash diff {s["variance"]:+,.0f}')
    parts.append(f'Purchases {s["purchases_total"]:,.0f}')
    parts.append(f'Low stock {s["low_stock"]}, expiring 30d {s["expiring"]}')
    return '. '.join(parts)[:306]


def email_text(store, day, s):
    lines = [
        f'{store.name} — end of day {day:%A %d %B %Y}', '',
        f'Sales: TZS {s["sales_total"]:,.0f} from {s["sales_count"]} sale(s)',
        *[f'  {name}: TZS {total:,.0f}' for name, total in s['by_method']],
        f'Voided sales: {s["void_count"]}',
        f'Sales without an EFD receipt number: {s["missing_efd"]}',
        f'Cash difference at shift close: TZS {s["variance"]:+,.0f}',
        f'Supplier invoices received: TZS {s["purchases_total"]:,.0f}',
        f'Products low or out of stock: {s["low_stock"]}',
        f'Batches expiring within 30 days: {s["expiring"]}',
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
                    body = email_text(store, today, stats) if key == NotificationLog.Channel.EMAIL else sms_text(store, today, stats)
                    success, error = True, ''
                    try:
                        channel.send(address, f'{store.name} — end of day {today:%d/%m/%Y}', body)
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
