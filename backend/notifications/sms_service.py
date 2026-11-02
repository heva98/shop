"""Building and sending SMS batches.

    audience code (sms_audiences) → list of Recipient
    → create_batch(): checks, fill in templates, save 1 SmsBatch + N SmsMessage
    → send_batch(): call the provider for every PENDING row, in chunks

Every recipient gets a saved row, skipped ones too, with the reason.
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.phone import is_tz_mobile, normalize_tz_phone

from .models import SmsBatch, SmsConfiguration, SmsMessage, SmsTemplate
from .sms_backends import get_sms_backend
from .sms_segments import count_segments
from .sms_templates import DEFAULT_TEMPLATES, MissingPlaceholder, check_template, render

Skip = SmsMessage.SkipReason


@dataclass
class Recipient:
    phone: str
    template_key: str
    language: str
    values: dict = field(default_factory=dict)
    user: object = None
    name: str = ''
    store: object = None
    skip_reason: str = ''  # set by the audience code, e.g. Skip.NO_PHONE


class BatchTooLarge(Exception):
    pass


def limits(config):
    """(recipient cap, max segments): per-shop values can only lower the server's."""
    cap, segments = settings.SMS_BATCH_RECIPIENT_CAP, settings.SMS_MAX_SEGMENTS
    if config.batch_recipient_cap:
        cap = min(cap, config.batch_recipient_cap)
    if config.max_segments:
        segments = min(segments, config.max_segments)
    return cap, segments


def ensure_templates(entity, force=False):
    """Creates any missing template from the defaults; force resets edited ones."""
    for (key, language), body in DEFAULT_TEMPLATES.items():
        template, created = SmsTemplate.objects.get_or_create(
            entity=entity, key=key, language=language, defaults={'body': body})
        if force and not created and (template.body != body or not template.is_active):
            template.body, template.is_active = body, True
            template.save()


def _active_templates(entity):
    ensure_templates(entity)
    return {(t.key, t.language): t.body for t in SmsTemplate.objects.filter(entity=entity, is_active=True)}


def price(segments):
    return Decimal(str(settings.SMS_PRICE_PER_SEGMENT)) * segments


def evaluate(recipients, templates, max_segments):
    """The checks, in order; the first that fails decides. Yields
    (recipient, phone, body, segments, skip_reason)."""
    seen = set()
    for r in recipients:
        phone = normalize_tz_phone(r.phone) or ''
        body, segments, reason = '', 0, r.skip_reason
        template = templates.get((r.template_key, r.language))
        if not reason and template is None:
            reason = Skip.NO_TEMPLATE
        if not reason and not is_tz_mobile(phone):
            reason = Skip.INVALID_PHONE
        store_id = getattr(r.store, 'pk', None)
        if not reason and (phone, store_id) in seen:
            reason = Skip.DUPLICATE
        if not reason:
            try:
                body = render(template, r.values)
            except MissingPlaceholder:
                reason = Skip.MISSING_VALUE
        if not reason:
            segments = count_segments(body)
            if segments > max_segments:
                reason = Skip.TOO_LONG
        if not reason:
            seen.add((phone, store_id))
        yield r, phone or (r.phone or ''), body, segments if not reason else 0, reason


def _check_syntax(templates, recipients):
    for key in {r.template_key for r in recipients}:
        for (k, _lang), body in templates.items():
            if k == key:
                check_template(body, key)


def preview_recipients(entity, recipients, sample_size=3):
    """Same checks as create_batch, nothing saved."""
    config = SmsConfiguration.load(entity)
    _cap, max_segments = limits(config)
    templates = _active_templates(entity)
    _check_syntax(templates, recipients)
    would_send, skipped, breakdown, samples, segments = 0, 0, {}, [], 0
    for r, phone, body, seg, reason in evaluate(recipients, templates, max_segments):
        if reason:
            skipped += 1
            breakdown[reason] = breakdown.get(reason, 0) + 1
            continue
        would_send += 1
        segments += seg
        if len(samples) < sample_size:
            samples.append({'to': r.name, 'phone': phone, 'store': getattr(r.store, 'name', ''),
                            'body': body, 'segments': seg})
    return {
        'would_send': would_send, 'skipped': skipped,
        'skip_breakdown': [{'reason': k, 'label': str(Skip(k).label), 'count': v} for k, v in breakdown.items()],
        'samples': samples, 'total_segments': segments,
        'total_cost': price(segments) if settings.SMS_PRICE_PER_SEGMENT else None,
    }


def create_batch(entity, kind, recipients, *, idempotency_key='', dry_run=False, created_by=None, context=None):
    """Saves the batch and one row per recipient. Returns the existing
    batch if idempotency_key was already used (also when two callers race)."""
    if idempotency_key:
        existing = SmsBatch.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing
    config = SmsConfiguration.load(entity)
    cap, max_segments = limits(config)
    if len(recipients) > cap:
        raise BatchTooLarge(f'{len(recipients)} recipients is more than the limit of {cap}.')
    templates = _active_templates(entity)
    _check_syntax(templates, recipients)
    backend = get_sms_backend()
    try:
        with transaction.atomic():
            batch = SmsBatch.objects.create(
                entity=entity, kind=kind, dry_run=dry_run, context=context or {}, created_by=created_by,
                idempotency_key=idempotency_key, sender_id=backend.default_sender_id(),
            )
            rows = []
            for r, phone, body, seg, reason in evaluate(recipients, templates, max_segments):
                rows.append(SmsMessage(
                    batch=batch, store=r.store, recipient=r.user, recipient_name=r.name, phone=phone, body=body,
                    status=SmsMessage.Status.SKIPPED if reason else SmsMessage.Status.PENDING,
                    skip_reason=reason, segments=seg, cost=price(seg),
                ))
            SmsMessage.objects.bulk_create(rows)
            pending = [m for m in rows if m.status == SmsMessage.Status.PENDING]
            batch.skipped_count = len(rows) - len(pending)
            batch.total_segments = sum(m.segments for m in pending)
            batch.total_cost = sum((m.cost for m in pending), Decimal(0))
            if pending and not dry_run:
                batch.status = SmsBatch.Status.QUEUED
            else:
                batch.status, batch.completed_at = SmsBatch.Status.COMPLETED, timezone.now()
            batch.save()
    except IntegrityError:
        if idempotency_key:
            existing = SmsBatch.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                return existing
        raise
    return batch


def refresh_totals(batch):
    counts = batch.messages.aggregate(
        sent=Count('id', filter=Q(status__in=[SmsMessage.Status.SENT, SmsMessage.Status.DELIVERED])),
        failed=Count('id', filter=Q(status=SmsMessage.Status.FAILED)),
        skipped=Count('id', filter=Q(status=SmsMessage.Status.SKIPPED)),
        segments=Sum('segments', filter=~Q(status=SmsMessage.Status.SKIPPED)),
        cost=Sum('cost', filter=~Q(status=SmsMessage.Status.SKIPPED)),
    )
    batch.sent_count, batch.failed_count, batch.skipped_count = counts['sent'], counts['failed'], counts['skipped']
    batch.total_segments, batch.total_cost = counts['segments'] or 0, counts['cost'] or Decimal(0)


def send_batch(batch_id):
    """Sends only rows still PENDING, so a retry never sends one twice."""
    batch = SmsBatch.objects.get(pk=batch_id)
    if batch.dry_run:
        return batch
    batch.status = SmsBatch.Status.RUNNING
    batch.save(update_fields=['status'])
    backend = get_sms_backend()
    chunk = max(1, settings.SMS_PROVIDER_CHUNK_SIZE)
    pending = list(batch.messages.filter(status=SmsMessage.Status.PENDING))
    for start in range(0, len(pending), chunk):
        if start:
            time.sleep(settings.SMS_PROVIDER_CHUNK_SLEEP)
        for message in pending[start:start + chunk]:
            result = backend.send_one(message.phone, message.body, batch.sender_id)
            message.status = SmsMessage.Status.SENT if result.ok else SmsMessage.Status.FAILED
            message.error_detail = result.error
            message.provider_message_id = result.provider_message_id
            message.provider_status = result.provider_status
            message.provider_response = result.raw
            message.sent_at = timezone.now() if result.ok else None
            message.save(update_fields=['status', 'error_detail', 'provider_message_id', 'provider_status',
                                        'provider_response', 'sent_at'])
    refresh_totals(batch)
    nothing_sent = batch.sent_count == 0 and batch.failed_count > 0
    batch.status = SmsBatch.Status.FAILED if nothing_sent else SmsBatch.Status.COMPLETED
    batch.completed_at = timezone.now()
    batch.save()
    return batch


def requeue_failed(batch):
    """FAILED rows back to PENDING, ready to send again. Returns how many."""
    count = batch.messages.filter(status=SmsMessage.Status.FAILED).update(
        status=SmsMessage.Status.PENDING, error_detail='')
    if count:
        batch.status = SmsBatch.Status.QUEUED
        batch.save(update_fields=['status'])
    return count
