"""The SMS jobs. This project has no task queue: send_daily_summaries runs
daily_sales_sms_run() from the systemd timer (deploy/systemd/
shop-daily-summary.timer, 21:30), off the web request.

Re-running is safe: the day's batch is found again by its idempotency
key and only rows still PENDING are sent.
"""

import logging

from django.utils import timezone

from core.models import Entity

from .models import SmsBatch, SmsMessage
from .sms_audiences import daily_sales_recipients
from .sms_service import create_batch, send_batch

logger = logging.getLogger('notifications.sms')


def run_sms_batch(batch_id):
    """send_batch(), marking the batch FAILED if it blows up part-way;
    rows already sent stay SENT, so running it again only sends the rest."""
    try:
        return send_batch(batch_id)
    except Exception:  # noqa: BLE001 — record it; the next run picks up what's left
        logger.exception('SMS batch %s failed', batch_id)
        SmsBatch.objects.filter(pk=batch_id).update(status=SmsBatch.Status.FAILED)
        return SmsBatch.objects.get(pk=batch_id)


def daily_sales_idempotency_key(entity, day):
    return f'daily-sales-{entity.pk}-{day:%Y-%m-%d}'


def daily_sales_sms_run(day=None):
    """Today's sales summary to every shop's owner. Returns the batches."""
    day = day or timezone.localdate()
    batches = []
    for entity in Entity.objects.filter(is_active=True):
        recipients = daily_sales_recipients(entity, day)
        if not recipients:
            continue
        try:
            batch = create_batch(
                entity, SmsBatch.Kind.DAILY_SALES_SUMMARY, recipients,
                idempotency_key=daily_sales_idempotency_key(entity, day),
                context={'date': day.isoformat(), 'audience': 'owners', 'trigger': 'schedule',
                         'stores': sorted({r.store.name for r in recipients})},
            )
        except Exception:  # noqa: BLE001 — one shop's bad template mustn't stop the others
            logger.exception('Daily sales SMS for %s could not be built', entity)
            continue
        if batch.messages.filter(status=SmsMessage.Status.PENDING).exists():
            batch = run_sms_batch(batch.pk)
        if batch.failed_count:
            logger.error('Daily sales SMS for %s: %s message(s) failed', entity, batch.failed_count)
        batches.append(batch)
    return batches
