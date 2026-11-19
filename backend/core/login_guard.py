"""Limits on guessing passwords, shared by every place that checks one:
sign-in (core.auth_views) and a manager's approval typed in at the till
(pos.views). Both count toward the same limits, so the till is not a
side door for guessing a manager's or owner's password.

Wrong passwords are counted from the audit log's failed sign-ins, over
the last LOGIN_LOCKOUT_MINUTES:

- one username from one address: LOGIN_LOCKOUT_ATTEMPTS (since that
  username's last successful sign-in). Someone guessing is stopped, but
  a stranger elsewhere cannot lock an owner out of their own shop.
- one username from anywhere: LOGIN_LOCKOUT_GLOBAL_ATTEMPTS, against
  guessing spread over many addresses.
- one address, any username: LOGIN_IP_LOCKOUT_ATTEMPTS, against trying
  one common password on many accounts.

Reaching a limit writes a LOGIN_LOCKED event with data.scope ('user' or
'ip'); audit.alerts tells the shop's owners (or, for an address, the
platform administrator)."""

import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.throttling import SimpleRateThrottle

from audit.models import AuditEvent
from audit.services import Action, Summary, client_ip, record


class LockedOut(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = 'locked_out'


def normalize_username(username):
    """A self-registered owner's username is their number, 0712345678
    (core.signup); let them type it as 0712 345 678 or +255 712 345 678."""
    username = (username or '').strip()
    if not re.fullmatch(r'[\d\s+\-()]+', username):
        return username
    digits = re.sub(r'\D', '', username)
    if len(digits) == 12 and digits.startswith('255'):
        digits = '0' + digits[3:]
    if digits != username and get_user_model().objects.filter(username__iexact=digits).exists():
        return digits
    return username


def _window_start():
    return timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def _failures():
    return AuditEvent.objects.filter(action=Action.LOGIN_FAILED, created_at__gt=_window_start())


def _user_failures(username):
    """Failures for `username` since its last successful sign-in."""
    last_success = (AuditEvent.objects.filter(username__iexact=username, action=Action.LOGIN)
                    .order_by('-created_at').values_list('created_at', flat=True).first())
    failures = _failures().filter(username__iexact=username)
    return failures.filter(created_at__gt=last_success) if last_success else failures


def _counts(username, ip):
    user_failures = _user_failures(username)
    return {
        'pair': user_failures.filter(ip_address=ip).count() if ip else 0,
        'user': user_failures.count(),
        'ip': _failures().filter(ip_address=ip).count() if ip else 0,
    }


def _limits():
    return {
        'pair': settings.LOGIN_LOCKOUT_ATTEMPTS,
        'user': settings.LOGIN_LOCKOUT_GLOBAL_ATTEMPTS,
        'ip': settings.LOGIN_IP_LOCKOUT_ATTEMPTS,
    }


def lockout_scope(username, ip):
    """'ip' or 'user' when a limit has been reached, else None."""
    counts, limits = _counts(username, ip), _limits()
    if counts['ip'] >= limits['ip']:
        return 'ip'
    if counts['pair'] >= limits['pair'] or counts['user'] >= limits['user']:
        return 'user'
    return None


def refuse_if_locked(request, username):
    """Raises LockedOut (429) when `username`, or this address, has had
    too many wrong passwords; the refusal itself is logged."""
    scope = lockout_scope(username, client_ip(request))
    if scope is None:
        return
    record(Action.LOGIN_LOCKED, Summary('Sign-in refused for "{username}": too many wrong passwords', username=username),
           request=request, username=username, entity=_entity_of(username), data={'refused': True, 'scope': scope})
    minutes = settings.LOGIN_LOCKOUT_MINUTES
    if scope == 'ip':
        message = gettext('Too many wrong passwords from this connection. Try again in {minutes} minutes.')
    else:
        message = gettext('Too many wrong passwords. Try again in {login_lockout_minutes} minutes, or ask your administrator to reset your password.')
    raise LockedOut(message.format(minutes=minutes, login_lockout_minutes=minutes))


def _entity_of(username):
    known = get_user_model().objects.filter(username__iexact=username).select_related('entity').first()
    return getattr(known, 'entity', None)


def record_failure(request, username, summary):
    """Logs one wrong password for `username`, and a LOGIN_LOCKED event
    the moment a limit is reached (which audit.alerts reports)."""
    entity = _entity_of(username)
    record(Action.LOGIN_FAILED, summary, request=request, username=username, entity=entity)
    ip = client_ip(request)
    counts, limits = _counts(username, ip), _limits()
    if counts['ip'] == limits['ip']:
        record(Action.LOGIN_LOCKED,
               Summary('Address {ip} blocked: {count} wrong passwords for different users', ip=ip, count=counts['ip']),
               request=request, username=username, entity=None,
               data={'scope': 'ip', 'reached': True, 'failures': counts['ip']})
    if counts['pair'] == limits['pair'] or counts['user'] == limits['user']:
        record(Action.LOGIN_LOCKED,
               Summary('"{username}" locked out after {count} wrong passwords', username=username,
                       count=max(counts['pair'], counts['user'])),
               request=request, username=username, entity=entity,
               data={'scope': 'user', 'reached': True, 'failures': counts['user']})


class AuthRateThrottle(SimpleRateThrottle):
    """Per-address ceiling on the public sign-in, sign-up and password
    reset endpoints (AUTH_THROTTLE_RATE; None switches it off). Keyed by
    audit.services.client_ip — nginx's X-Real-IP, which a client cannot
    forge, unlike X-Forwarded-For."""
    scope = 'auth'

    def get_rate(self):
        return settings.AUTH_THROTTLE_RATE

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': client_ip(request) or 'unknown'}
