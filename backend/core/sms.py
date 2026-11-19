"""The kernel's port for sending a text message.

The kernel must text one-time codes (sign-up, password reset) but must
not depend on the notifications module, which is pluggable. So it asks
for "whatever sends SMS" through the SMS_GATEWAY setting: the dotted path
of a function returning an object with `.sends` (bool) and
`.send_one(...)`. config/settings.py points it at the notifications
module's provider adapters; a deployment (or a test) can swap it without
touching core."""

from django.conf import settings
from django.utils.module_loading import import_string


def sms_gateway():
    return import_string(settings.SMS_GATEWAY)()
