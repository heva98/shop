"""SMS provider adapters. Everything else calls get_sms_backend().send_one()
and never sees a token.

SMS_BACKEND in .env picks one:
    noop           saves the rows, sends nothing (the default)
    console        same, and writes each message to the log
    notify_africa  sends through Notify Africa (NOTIFY_AFRICA_* settings)
    beem           sends through Beem Africa (BEEM_* settings)

send_one() never raises: every failure comes back as SmsResult(ok=False)
with a short error code the delivery log can show.
"""

import base64
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

BEEM_URL = 'https://apisms.beem.africa/v1/send'
CREDIT_WORDS = ('insufficient', 'low balance', 'no credit', 'not enough credit', 'out of credit')
FAILED_STATUSES = ('failed', 'error', 'rejected')


@dataclass
class SmsResult:
    ok: bool
    provider_message_id: str = ''
    provider_status: str = ''
    error: str = ''
    raw: dict = field(default_factory=dict)


class SmsBackend:
    name = ''
    sends = False  # True when messages really leave the server

    @property
    def configured(self):
        return True

    def default_sender_id(self):
        return ''

    def send_one(self, to, body, sender_id) -> SmsResult:
        raise NotImplementedError


class NoopBackend(SmsBackend):
    name = 'noop'

    def send_one(self, to, body, sender_id):
        return SmsResult(ok=True, provider_status='noop')


class ConsoleBackend(SmsBackend):
    name = 'console'

    def send_one(self, to, body, sender_id):
        logger.info('SMS (console, not sent) to %s: %s', to, body)
        return SmsResult(ok=True, provider_status='console')


def _post_json(request, timeout):
    """(status, parsed body or {'text': …}) — or raises URLError/TimeoutError."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, text = getattr(response, 'status', 200), response.read().decode(errors='replace')
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode(errors='replace')
    try:
        body = json.loads(text or '{}')
    except ValueError:
        body = {'text': text[:500]}
    return status, body if isinstance(body, dict) else {'data': body}


def _classify(status, body):
    """The error code for a refused send, or '' when it went through."""
    text = json.dumps(body).lower()
    if status in (401, 403):
        return 'unauthorized'
    if status == 402 or any(word in text for word in CREDIT_WORDS):
        return 'insufficient_credit'
    if not 200 <= status < 300:
        return f'http_{status}'
    return ''


class NotifyAfricaBackend(SmsBackend):
    name = 'notify_africa'
    sends = True

    @property
    def configured(self):
        return bool(settings.NOTIFY_AFRICA_BASE_URL and settings.NOTIFY_AFRICA_API_TOKEN
                    and settings.NOTIFY_AFRICA_SENDER_ID)

    def default_sender_id(self):
        return settings.NOTIFY_AFRICA_SENDER_ID

    def send_one(self, to, body, sender_id):
        url = settings.NOTIFY_AFRICA_BASE_URL.rstrip('/') + '/api/v1/api/messages/send'
        payload = json.dumps({
            'phone_number': to.lstrip('+'), 'message': body, 'sender_id': str(sender_id),
        }).encode()
        request = urllib.request.Request(url, data=payload, method='POST', headers={
            'Authorization': f'Bearer {settings.NOTIFY_AFRICA_API_TOKEN}', 'Content-Type': 'application/json',
        })
        try:
            status, raw = _post_json(request, settings.NOTIFY_AFRICA_TIMEOUT)
        except TimeoutError:
            return SmsResult(ok=False, error='timeout')
        except urllib.error.URLError as exc:
            return SmsResult(ok=False, error='timeout' if isinstance(exc.reason, TimeoutError) else 'connection_error')
        data = raw.get('data') if isinstance(raw.get('data'), dict) else {}
        provider_status = str(data.get('status') or raw.get('status') or '')
        error = _classify(status, raw)
        if not error and (str(raw.get('status', '')).lower() in FAILED_STATUSES
                          or provider_status.lower() in FAILED_STATUSES or raw.get('success') is False):
            error = 'rejected'
        if error:
            return SmsResult(ok=False, provider_status=provider_status, error=error, raw=raw)
        message_id = data.get('messageId') or data.get('message_id') or data.get('id') or ''
        return SmsResult(ok=True, provider_message_id=str(message_id), provider_status=provider_status, raw=raw)


class BeemBackend(SmsBackend):
    """Kept so shops already set up with Beem keep working."""
    name = 'beem'
    sends = True

    @property
    def configured(self):
        return bool(settings.BEEM_API_KEY and settings.BEEM_SECRET_KEY and settings.BEEM_SENDER_ID)

    def default_sender_id(self):
        return settings.BEEM_SENDER_ID

    def send_one(self, to, body, sender_id):
        credentials = base64.b64encode(f'{settings.BEEM_API_KEY}:{settings.BEEM_SECRET_KEY}'.encode()).decode()
        payload = json.dumps({
            'source_addr': sender_id, 'encoding': 0, 'schedule_time': '', 'message': body,
            'recipients': [{'recipient_id': 1, 'dest_addr': to.lstrip('+')}],
        }).encode()
        request = urllib.request.Request(BEEM_URL, data=payload, method='POST', headers={
            'Authorization': f'Basic {credentials}', 'Content-Type': 'application/json',
        })
        try:
            status, raw = _post_json(request, 20)
        except TimeoutError:
            return SmsResult(ok=False, error='timeout')
        except urllib.error.URLError:
            return SmsResult(ok=False, error='connection_error')
        error = _classify(status, raw)
        if not error and ((not raw.get('successful') and raw.get('code') != 100) or raw.get('invalid')):
            error = 'rejected'
        return SmsResult(ok=not error, provider_message_id=str(raw.get('request_id') or ''),
                         provider_status=str(raw.get('code') or ''), error=error, raw=raw)


BACKENDS = {cls.name: cls for cls in (NoopBackend, ConsoleBackend, NotifyAfricaBackend, BeemBackend)}


def get_sms_backend():
    return BACKENDS.get(settings.SMS_BACKEND, NoopBackend)()
