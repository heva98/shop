"""POST /api/auth-token/ — sign-in. See core.authentication for the
session rules; this adds the lockout after repeated wrong passwords,
counted from the audit log's failed sign-ins."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.utils import timezone
from rest_framework import exceptions, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.models import AuditEvent
from audit.services import Action, record

from .authentication import SHOP_SUSPENDED_MESSAGE, shop_suspended


def _recent_failures(username):
    window_start = timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
    last_success = (AuditEvent.objects.filter(username__iexact=username, action=Action.LOGIN)
                    .order_by('-created_at').values_list('created_at', flat=True).first())
    since = max(window_start, last_success) if last_success else window_start
    return AuditEvent.objects.filter(
        username__iexact=username, action=Action.LOGIN_FAILED, created_at__gt=since,
    ).count()


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([])
def obtain_token(request):
    """POST {username, password} -> {token, must_change_password}."""
    username = (request.data.get('username') or '').strip()
    password = request.data.get('password') or ''
    if not username or not password:
        raise exceptions.ValidationError({'non_field_errors': ['Enter your username and password.']})

    if _recent_failures(username) >= settings.LOGIN_LOCKOUT_ATTEMPTS:
        record(Action.LOGIN_LOCKED, f'Sign-in refused for "{username}": too many wrong passwords',
               request=request, username=username)
        return Response(
            {'detail': f'Too many wrong passwords. Try again in {settings.LOGIN_LOCKOUT_MINUTES} minutes, '
                       'or ask your administrator to reset your password.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = authenticate(request, username=username, password=password)
    if user is None:
        known = get_user_model().objects.filter(username__iexact=username).first()
        record(Action.LOGIN_FAILED, f'Wrong password for "{username}"', request=request,
               username=username, entity=getattr(known, 'entity', None))
        raise exceptions.ValidationError({'non_field_errors': ['Unable to log in with provided credentials.']})

    if shop_suspended(user):
        raise exceptions.PermissionDenied(SHOP_SUSPENDED_MESSAGE)

    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    record(Action.LOGIN, f'{user.username} signed in', request=request, user=user)
    return Response({'token': token.key, 'must_change_password': user.must_change_password})
