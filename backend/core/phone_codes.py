"""One-time codes sent by SMS: sign-up proves the number is the person's,
and "Forgot password?" lets a user choose a new password without an
administrator. A code is six digits, lasts PHONE_CODE_MINUTES and allows
PHONE_CODE_ATTEMPTS guesses; only its HMAC is stored.

send_code() and check_code() raise ValidationError with a message for the
person, so the views just let it through."""

import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers

from audit.services import client_ip

from .models import PhoneCode
from .phone import is_tz_mobile, normalize_tz_phone
from .sms import sms_gateway

logger = logging.getLogger(__name__)


def _new_code():
    return f'{secrets.randbelow(1_000_000):06d}'


def _hash(phone, purpose, code):
    message = f'{phone}:{purpose}:{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def masked(phone):
    """255712345678 → '0712 ••• 678', to say where a code went."""
    local = '0' + phone[3:] if phone.startswith('255') else phone
    return f'{local[:4]} ••• {local[-3:]}'


def send_code(phone, purpose, *, request=None, user=None):
    """Texts a new code to `phone` (stored form, 255712345678). Returns
    {sent_to, minutes} plus, on a development server whose SMS backend
    sends nothing, the code itself as debug_code."""
    sms_to = normalize_tz_phone(phone)
    if not is_tz_mobile(sms_to):
        raise serializers.ValidationError({'phone': [gettext('Enter a Tanzanian mobile number, e.g. 0712 345 678.')]})
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)
    ip = client_ip(request)
    if (PhoneCode.objects.filter(phone=phone, created_at__gt=hour_ago).count() >= settings.PHONE_CODE_PER_PHONE_HOURLY
            or (ip and PhoneCode.objects.filter(ip_address=ip, created_at__gt=hour_ago).count() >= settings.PHONE_CODE_PER_IP_HOURLY)):
        raise serializers.ValidationError({'detail': gettext('Too many codes were requested. Wait an hour and try again.')})

    backend = sms_gateway()
    if not backend.sends and not settings.DEBUG:
        logger.error('A phone code was requested but SMS_BACKEND=%s sends nothing.', settings.SMS_BACKEND)
        raise serializers.ValidationError({'detail': gettext(
            'SMS codes are not set up on this server yet. Contact the system administrator.')})
    code = _new_code()
    minutes = settings.PHONE_CODE_MINUTES
    PhoneCode.objects.filter(phone=phone, purpose=purpose, used_at__isnull=True).update(used_at=now)  # one live code at a time
    PhoneCode.objects.create(phone=phone, purpose=purpose, user=user, code_hash=_hash(phone, purpose, code),
                             ip_address=ip, expires_at=now + timedelta(minutes=minutes))
    body = gettext('{code} is your Shoppy code. It expires in {minutes} minutes. Do not share it with anyone.').format(
        code=code, minutes=minutes)
    result = backend.send_one(sms_to, body, backend.default_sender_id())
    if not result.ok:
        logger.error('Phone code SMS to %s failed: %s', sms_to, result.error)
        raise serializers.ValidationError({'detail': gettext('The SMS could not be sent. Try again in a few minutes.')})
    reply = {'sent_to': masked(phone), 'minutes': minutes}
    if not backend.sends:  # a development server (DEBUG) whose SMS goes nowhere
        reply['debug_code'] = code
    return reply


def check_code(phone, purpose, code, *, user=None):
    """Uses up the live code for `phone` if `code` matches it; otherwise
    counts the guess and raises ValidationError({'code': …})."""
    code = ''.join(ch for ch in str(code or '') if ch.isdigit())
    live = (PhoneCode.objects.filter(phone=phone, purpose=purpose, used_at__isnull=True, expires_at__gt=timezone.now())
            .order_by('-created_at').first())
    if live is None or (user is not None and live.user_id != user.pk):
        raise serializers.ValidationError({'code': [gettext('This code has expired. Ask for a new one.')]})
    if live.attempts >= settings.PHONE_CODE_ATTEMPTS:
        raise serializers.ValidationError({'code': [gettext('Too many wrong codes. Ask for a new one.')]})
    if not hmac.compare_digest(live.code_hash, _hash(phone, purpose, code)):
        PhoneCode.objects.filter(pk=live.pk).update(attempts=live.attempts + 1)
        raise serializers.ValidationError({'code': [gettext('That code is not right. Check the SMS and try again.')]})
    live.used_at = timezone.now()
    live.save(update_fields=['used_at'])
    return live
