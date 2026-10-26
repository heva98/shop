"""SMS through Beem Africa (https://beem.africa), a Tanzanian SMS gateway
that delivers to Vodacom, Yas (Tigo), Airtel and Halotel numbers.

Configure in .env:
    SMS_PROVIDER=beem
    BEEM_API_KEY=...        from the Beem dashboard (Profile > Authentication information)
    BEEM_SECRET_KEY=...
    BEEM_SENDER_ID=...      an approved sender name, e.g. KILIMANIPH (Beem's default is INFO)

With SMS_PROVIDER unset, messages are only written to the log —
`configured` is False so callers can say so instead of pretending a
message went out. Uses only the standard library (no extra dependency).
"""

import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings

from notifications.interfaces import NotificationChannel

logger = logging.getLogger(__name__)

BEEM_URL = 'https://apisms.beem.africa/v1/send'


class SMSError(Exception):
    pass


class SMSChannel(NotificationChannel):
    @property
    def configured(self):
        return (settings.SMS_PROVIDER == 'beem'
                and bool(settings.BEEM_API_KEY and settings.BEEM_SECRET_KEY and settings.BEEM_SENDER_ID))

    def send(self, recipient: str, subject: str, body: str) -> bool:
        """`recipient` is a phone number in international form
        (255712345678). `subject` is unused for SMS. Raises SMSError when
        the gateway refuses the message, so the caller can record why."""
        if not self.configured:
            logger.info('SMS (not sent, no provider configured) to %s: %s', recipient, body)
            return False
        credentials = base64.b64encode(f'{settings.BEEM_API_KEY}:{settings.BEEM_SECRET_KEY}'.encode()).decode()
        payload = json.dumps({
            'source_addr': settings.BEEM_SENDER_ID,
            'encoding': 0,
            'schedule_time': '',
            'message': body,
            'recipients': [{'recipient_id': 1, 'dest_addr': recipient}],
        }).encode()
        request = urllib.request.Request(BEEM_URL, data=payload, method='POST', headers={
            'Authorization': f'Basic {credentials}', 'Content-Type': 'application/json',
        })
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[:300]
            raise SMSError(f'Beem refused the message (HTTP {exc.code}): {detail}') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SMSError(f'Could not reach Beem: {exc}') from exc
        if not result.get('successful') and result.get('code') != 100:
            raise SMSError(f'Beem did not accept the message: {result.get("message") or result}')
        if result.get('invalid'):
            raise SMSError(f'Beem rejected the number {recipient} as invalid.')
        return True
