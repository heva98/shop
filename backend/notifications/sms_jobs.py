"""The SMS jobs. This project has no task queue: send_daily_summaries runs
daily_sales_sms_run() from the systemd timer (deploy/systemd/
shop-daily-summary.timer, every 5 minutes), off the web request.

Each owner has their own send time (User.daily_sms_time, set in the Shops
console), so a shop's day can take several batches: each run sends to
whoever's time has come and has no row in one of today's batches yet.
Re-running is safe: rows still PENDING in today's batches are sent, and
nobody already in one is added again.
"""

import logging

from django.db.models import Q
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
    """The day's key; each batch adds -HHMM, the time of the run."""
    return f'daily-sales-{entity.pk}-{day:%Y-%m-%d}'


def todays_batches(entity, day):
    key = daily_sales_idempotency_key(entity, day)
    return SmsBatch.objects.filter(
        Q(idempotency_key=key) | Q(idempotency_key__startswith=f'{key}-'),
        entity=entity, kind=SmsBatch.Kind.DAILY_SALES_SUMMARY,
    )


def daily_sales_sms_run(now=None):
    """Today's sales summary to every owner whose send time has come.
    Returns the batches created or sent this run."""
    now = timezone.localtime(now)
    day = now.date()
    batches = []
    for entity in Entity.objects.filter(is_active=True):
        earlier = todays_batches(entity, day)
        handled = set(SmsMessage.objects.filter(batch__in=earlier).values_list('recipient_id', 'store_id'))
        recipients = daily_sales_recipients(entity, day, due_at=now.time(), exclude=handled)
        created = None
        if recipients:
            try:
                created = create_batch(
                    entity, SmsBatch.Kind.DAILY_SALES_SUMMARY, recipients,
                    idempotency_key=f'{daily_sales_idempotency_key(entity, day)}-{now:%H%M}',
                    context={'date': day.isoformat(), 'audience': 'owners', 'trigger': 'schedule',
                             'stores': sorted({r.store.name for r in recipients})},
                )
            except Exception:  # noqa: BLE001 — one shop's bad template mustn't stop the others
                logger.exception('Daily sales SMS for %s could not be built', entity)
        unsent = todays_batches(entity, day).filter(messages__status=SmsMessage.Status.PENDING).distinct()
        for batch in unsent:
            batch = run_sms_batch(batch.pk)
            if batch.failed_count:
                logger.error('Daily sales SMS for %s: %s message(s) failed', entity, batch.failed_count)
            batches.append(batch)
        if created and created.pk not in {b.pk for b in batches}:
            batches.append(created)  # all skipped: still reported
    return batches
