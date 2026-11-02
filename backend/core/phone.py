"""Tanzanian phone numbers for SMS. User.phone is stored as 255712345678
(core.serializers.normalize_phone); SMS rows keep the +255 form."""

import re

TZ_MOBILE = re.compile(r'^\+255[67]\d{8}$')


def normalize_tz_phone(value):
    """0713…, 255713…, +255 713 …, 713… and 00255… → '+255713…'; anything
    that isn't a nine-digit Tanzanian number → None."""
    digits = re.sub(r'\D', '', value or '')
    if digits.startswith('00255'):
        digits = digits[2:]
    if digits.startswith('255') and len(digits) == 12:
        return '+' + digits
    if digits.startswith('0') and len(digits) == 10:
        return '+255' + digits[1:]
    if len(digits) == 9 and not digits.startswith('0'):
        return '+255' + digits
    return None


def is_tz_mobile(value):
    """Only +255 6x / 7x numbers can receive SMS."""
    return bool(value and TZ_MOBILE.match(value))
