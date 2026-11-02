"""How many SMS a text costs. GSM-7 fits 160 characters in one SMS or 153
per part when split; one character outside GSM-7 switches the whole text
to UCS-2, which fits 70, or 67 per part. Extension characters count 2."""

import math

GSM7_BASIC = set(
    '@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?'
    '¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà'
)
GSM7_EXTENDED = set('^{}\\[~]|€\f')


def encoding(text):
    return 'GSM-7' if all(c in GSM7_BASIC or c in GSM7_EXTENDED for c in text) else 'UCS-2'


def count_segments(text):
    if not text:
        return 0
    if encoding(text) == 'GSM-7':
        length = sum(2 if c in GSM7_EXTENDED else 1 for c in text)
        single, part = 160, 153
    else:
        # Characters outside the Basic Multilingual Plane (emoji) take two UCS-2 units.
        length = sum(2 if ord(c) > 0xFFFF else 1 for c in text)
        single, part = 70, 67
    return 1 if length <= single else math.ceil(length / part)
