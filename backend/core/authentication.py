"""Session rules (the sign-in view itself is core.auth_views).

DRF's stock token never expires, so a till left signed in, or a token
copied off a shared computer, would work forever. Here a token lasts
TOKEN_TTL_HOURS from sign-in (a shift, by default), every sign-in issues
a fresh token, and repeated wrong passwords lock the username for a while.
"""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token


class ExpiringTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if token.created < timezone.now() - timedelta(hours=settings.TOKEN_TTL_HOURS):
            token.delete()
            raise exceptions.AuthenticationFailed('Your session has expired. Sign in again.')
        return user, token


def revoke_sessions(user):
    """Signs the user out everywhere — after a password reset or when the
    account is disabled."""
    Token.objects.filter(user=user).delete()
