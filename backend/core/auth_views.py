"""POST /api/auth-token/ — sign-in, and POST /api/auth-token/logout/.
See core.authentication for the session rules, and core.login_guard for
the limits on wrong passwords (per username and address, per username,
per address) and the per-address request ceiling."""

from django.contrib.auth import authenticate
from django.utils.translation import gettext
from rest_framework import exceptions, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from audit.services import Action, Summary, record

from .authentication import SHOP_SUSPENDED_MESSAGE, shop_suspended
from .login_guard import AuthRateThrottle, normalize_username, record_failure, refuse_if_locked


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthRateThrottle])
def obtain_token(request):
    """POST {username, password} -> {token, must_change_password}."""
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not username or not password:
        raise exceptions.ValidationError({'non_field_errors': [gettext('Enter your username and password.')]})
    username = normalize_username(username)

    refuse_if_locked(request, username)

    user = authenticate(request, username=username, password=password)
    if user is None:
        record_failure(request, username, Summary('Wrong password for "{username}"', username=username))
        raise exceptions.ValidationError({'non_field_errors': [gettext('Unable to log in with provided credentials.')]})

    if shop_suspended(user):
        raise exceptions.PermissionDenied(SHOP_SUSPENDED_MESSAGE)

    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    record(Action.LOGIN, Summary('{username} signed in', username=user.username), request=request, user=user)
    return Response({'token': token.key, 'must_change_password': user.must_change_password})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def revoke_token(request):
    """POST /api/auth-token/logout/: ends this session on the server, so the
    token stops working even if it was copied off the device."""
    if isinstance(request.auth, Token):
        request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
