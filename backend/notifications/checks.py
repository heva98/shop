"""Refuse to start with a real SMS backend that lacks its credentials,
rather than quietly sending nothing."""

from django.conf import settings
from django.core.checks import Error, register

from .sms_backends import BACKENDS


@register()
def sms_backend_check(app_configs, **kwargs):
    backend = settings.SMS_BACKEND
    if backend not in BACKENDS:
        return [Error(f'SMS_BACKEND="{backend}" is not one of: {", ".join(BACKENDS)}.',
                      id='notifications.E003')]
    errors = []
    if backend == 'notify_africa':
        if not (settings.NOTIFY_AFRICA_API_TOKEN and settings.NOTIFY_AFRICA_BASE_URL):
            errors.append(Error('SMS_BACKEND=notify_africa needs NOTIFY_AFRICA_API_TOKEN and NOTIFY_AFRICA_BASE_URL.',
                                id='notifications.E001'))
        if not settings.NOTIFY_AFRICA_SENDER_ID:
            errors.append(Error('SMS_BACKEND=notify_africa needs NOTIFY_AFRICA_SENDER_ID (the numeric sender ID).',
                                id='notifications.E002'))
    if backend == 'beem' and not (settings.BEEM_API_KEY and settings.BEEM_SECRET_KEY and settings.BEEM_SENDER_ID):
        errors.append(Error('SMS_BACKEND=beem needs BEEM_API_KEY, BEEM_SECRET_KEY and BEEM_SENDER_ID.',
                            id='notifications.E001'))
    return errors
