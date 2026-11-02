"""`record()` is the one way to write an audit event. It never raises:
an audit failure must not stop the shop from trading, so it logs the
problem instead."""

import logging
from decimal import Decimal

from django.utils import translation
from django.utils.functional import Promise

from .models import AuditEvent

logger = logging.getLogger(__name__)
Action = AuditEvent.Action


class Summary(str):
    """An audit summary that keeps its English template and values, so the
    activity log can show it in each reader's language. The str itself is
    the English text, which is what gets stored and searched."""

    def __new__(cls, template, **params):
        # Stored in English whatever the writer's language: translated
        # labels among the values are resolved in English here.
        with translation.override('en'):
            params = {k: str(v) if isinstance(v, Promise) else v for k, v in params.items()}
            summary = super().__new__(cls, template.format(**params))
        summary.template = template
        summary.params = {k: float(v) if isinstance(v, Decimal) else v for k, v in params.items()}
        return summary


def client_ip(request):
    """The browser's address. Behind nginx the socket address is nginx
    itself, so X-Real-IP (which our nginx config sets from the connection,
    and a client cannot forge — unlike the first X-Forwarded-For entry)
    is used when present."""
    if request is None:
        return ''
    return (request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', ''))[:64]


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record(action, summary, *, request=None, user=None, store=None, entity=None, username='', data=None):
    try:
        if user is None and request is not None and getattr(request, 'user', None) and request.user.is_authenticated:
            user = request.user
        if entity is None:
            entity = store.entity if store is not None else getattr(user, 'entity', None)
        if isinstance(summary, Summary):
            data = {**(data or {}), '_summary': {'template': summary.template, 'params': summary.params}}
        AuditEvent.objects.create(
            action=action, summary=summary[:255], user=user,
            username=username or (user.username if user else ''),
            store=store, entity=entity, data=_jsonable(data or {}), ip_address=client_ip(request),
        )
    except Exception:  # noqa: BLE001 — see module docstring
        logger.exception('Could not write audit event %s', action)
