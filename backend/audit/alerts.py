"""Security alerts: the activity log records everything, but nobody reads
it until something is already wrong. These events are worth an owner's
attention straight away, so `manage.py send_security_alerts` (every 5
minutes, deploy/systemd/shop-security-alerts.timer) texts them to the
shop's owners, and emails owners who have an address:

- an offline sale at a price other than the store's (OFFLINE_SALE_PRICE),
  over the customer's credit limit or dated outside its shift
  (OFFLINE_SALE_LIMIT), or with a discount over the cashier's limit
  that no manager approved (DISCOUNT_GIVEN, data.unapproved)
- an account locked by wrong passwords, at sign-in or at the till's
  manager approval (LOGIN_LOCKED, data.reached, scope 'user')
- a new owner added to the shop (ROLE_GRANTED, data.role entity_admin);
  the new owner is not told about themselves

An address blocked for guessing across many accounts (LOGIN_LOCKED,
scope 'ip') belongs to no shop, so it goes to the platform's ADMINS.

Each alert is sent once (audit.SecurityAlert). An owner gets one SMS per
run with every new alert for their shop, cut to SMS_MAX_SEGMENTS."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.core.mail import mail_admins, send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone, translation
from django.utils.translation import gettext, ngettext

from core.models import Role, User
from core.phone import normalize_tz_phone
from core.sms import sms_gateway

from .models import AuditEvent, SecurityAlert
from .services import translated_summary

logger = logging.getLogger('audit.alerts')
Action = AuditEvent.Action

_SEGMENT = 153  # characters in each part of a multi-part SMS


@dataclass
class Alert:
    key: str
    event: AuditEvent
    exclude_usernames: set = field(default_factory=set)


def _due(since):
    """Every alert-worthy event since `since`, oldest first."""
    events = AuditEvent.objects.filter(created_at__gte=since).select_related('entity').order_by('created_at')
    alerts = []
    for event in events.filter(action__in=[Action.OFFLINE_SALE_PRICE, Action.OFFLINE_SALE_LIMIT]):
        alerts.append(Alert(f'event:{event.pk}', event))
    for event in events.filter(action=Action.DISCOUNT_GIVEN, data__unapproved=True):
        alerts.append(Alert(f'event:{event.pk}', event))
    for event in events.filter(action=Action.LOGIN_LOCKED, data__reached=True):
        alerts.append(Alert(f'event:{event.pk}', event))
    for event in events.filter(action=Action.ROLE_GRANTED, data__role=Role.ENTITY_ADMIN):
        alerts.append(Alert(f'event:{event.pk}', event, {(event.data or {}).get('user', '')}))
    return sorted(alerts, key=lambda a: a.event.created_at)


def _claim(alert):
    """True if this run is the first to take `alert`."""
    try:
        with transaction.atomic():
            SecurityAlert.objects.create(key=alert.key, entity=alert.event.entity,
                                         text=alert.event.summary[:500])
        return True
    except IntegrityError:
        return False


def _owners(entity):
    return User.objects.filter(entity=entity, is_active=True, store_roles__store__isnull=True,
                               store_roles__role=Role.ENTITY_ADMIN).distinct()


def compose(entity, events, limit):
    """The text for one owner, in the active language, at most `limit`
    characters: a heading, as many alerts as fit, and how many more."""
    head = gettext('Shoppy security alert for {shop}:').format(shop=entity.name)
    tail = gettext('Details: Activity log.')
    lines = [translated_summary(e) for e in events]
    for shown in range(len(lines), 0, -1):
        more = len(lines) - shown
        extra = [ngettext('...and {count} more.', '...and {count} more.', more).format(count=more)] if more else []
        text = ' '.join([head, *(f'- {line}' for line in lines[:shown]), *extra, tail])
        if len(text) <= limit:
            return text
    return f'{head} {ngettext("{count} new alert.", "{count} new alerts.", len(lines)).format(count=len(lines))} {tail}'[:limit]


def _send_to_owner(owner, entity, events, backend):
    """SMS and email to one owner; returns how many messages went."""
    sent = 0
    with translation.override(owner.language or 'en'):
        phone = normalize_tz_phone(owner.phone) if owner.phone else None
        if phone and backend.sends:
            text = compose(entity, events, _SEGMENT * max(1, settings.SMS_MAX_SEGMENTS))
            result = backend.send_one(phone, text, backend.default_sender_id())
            if result.ok:
                sent += 1
            else:
                logger.error('Security alert SMS to %s failed: %s', phone, result.error)
        if owner.email:
            subject = gettext('Shoppy security alert for {shop}').format(shop=entity.name)
            try:
                send_mail(subject, compose(entity, events, 5000), None, [owner.email])
                sent += 1
            except Exception:  # noqa: BLE001 — one bad address must not stop the rest
                logger.exception('Security alert email to %s failed', owner.email)
    return sent


def run(now=None):
    """Sends every alert not sent yet. Returns {'alerts': n, 'messages': m}."""
    now = now or timezone.now()
    since = now - timedelta(hours=settings.SECURITY_ALERTS_LOOKBACK_HOURS)
    claimed = [a for a in _due(since)
               if not SecurityAlert.objects.filter(key=a.key).exists() and _claim(a)]
    if not claimed:
        return {'alerts': 0, 'messages': 0}

    by_entity, platform = {}, []
    for alert in claimed:
        if alert.event.entity is None or (alert.event.data or {}).get('scope') == 'ip':
            platform.append(alert)
        else:
            by_entity.setdefault(alert.event.entity, []).append(alert)

    backend = sms_gateway()
    messages = 0
    for entity, alerts in by_entity.items():
        reached = 0
        for owner in _owners(entity):
            events = [a.event for a in alerts if owner.username not in a.exclude_usernames]
            if events:
                n = _send_to_owner(owner, entity, events, backend)
                messages += n
                reached += 1 if n else 0
        SecurityAlert.objects.filter(key__in=[a.key for a in alerts]).update(recipients=reached)
        if not reached:
            logger.warning('Security alerts for %s reached no owner (no phone/email, or SMS not set up)', entity.name)

    if platform:
        body = '\n'.join(f'{timezone.localtime(a.event.created_at):%Y-%m-%d %H:%M} {a.event.summary} '
                         f'[{a.event.ip_address}]' for a in platform)
        logger.warning('Platform security alerts:\n%s', body)
        mail_admins('Security alert: sign-in guessing', body, fail_silently=True)
        messages += 1 if settings.ADMINS else 0
    return {'alerts': len(claimed), 'messages': messages}
