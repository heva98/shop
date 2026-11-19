"""The public pages behind the sign-in screen, so a shop owner needs no
administrator to get started or back in:

    POST /api/signup/code/            {phone}                       texts a code
    POST /api/signup/                 {code, phone, password, first_name,
                                       last_name, shop: {...}, starter_products}
                                      creates the shop, its store and its owner
                                      (live at once) and signs the owner in
    POST /api/password-reset/code/    {username}                    texts a code
    POST /api/password-reset/         {username, code, new_password}
                                      sets the password and signs the user in

A self-registered owner signs in with their mobile number (0712345678) as
their username. The platform console (core.platform) can still suspend any
shop; SIGNUP_OPEN=False closes sign-up altogether."""

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.translation import get_language, gettext
from rest_framework import exceptions, serializers
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.services import Action, Summary, record
from catalog.seed_data import seed_catalog

from .authentication import revoke_sessions, shop_suspended
from .login_guard import AuthRateThrottle
from .models import PhoneCode, User
from .phone_codes import check_code, masked, send_code
from .platform import ShopSerializer
from .serializers import normalize_mobile

SHOP_FIELDS = ['name', 'business_type', 'country', 'region', 'council', 'address', 'tin', 'email']


def public(view):
    return api_view(['POST'])(authentication_classes([])(permission_classes([AllowAny])(throttle_classes([AuthRateThrottle])(view))))


def _require_open():
    if not settings.SIGNUP_OPEN:
        raise exceptions.PermissionDenied(gettext('New shops are registered by the system administrator.'))


def _phone(value):
    try:
        phone = normalize_mobile(value)
    except serializers.ValidationError as exc:
        raise serializers.ValidationError({'phone': exc.detail})
    if not phone:
        raise serializers.ValidationError({'phone': [gettext('Enter your mobile number, e.g. 0712 345 678.')]})
    return phone


def _username_for(phone):
    """255712345678 → '0712345678', the number as people write it."""
    return '0' + phone[3:]


def _number_taken(phone):
    if User.objects.filter(username__iexact=_username_for(phone)).exists():
        raise serializers.ValidationError({'phone': [gettext(
            'An account with this mobile number already exists. Sign in, or use “Forgot password?”.')]})


def _sign_in(request, user):
    Token.objects.filter(user=user).delete()
    token = Token.objects.create(user=user)
    record(Action.LOGIN, Summary('{username} signed in', username=user.username), request=request, user=user)
    return token.key


def _flatten(errors):
    """ShopSerializer's {owner: {field: [...]}} → {field: [...]} for the form."""
    flat = {}
    for field, value in errors.items():
        if isinstance(value, dict):
            flat.update(_flatten(value))
        else:
            flat[field] = value
    return flat


@public
def signup_code(request):
    _require_open()
    phone = _phone(request.data.get('phone'))
    _number_taken(phone)
    return Response(send_code(phone, PhoneCode.Purpose.SIGNUP, request=request))


@public
def signup(request):
    _require_open()
    data = request.data
    phone = _phone(data.get('phone'))
    _number_taken(phone)
    shop = data.get('shop') if isinstance(data.get('shop'), dict) else {}
    owner = {'username': _username_for(phone), 'phone': phone, 'password': data.get('password') or '',
             'first_name': (data.get('first_name') or '').strip(), 'last_name': (data.get('last_name') or '').strip()}
    serializer = ShopSerializer(data={**{k: shop[k] for k in SHOP_FIELDS if k in shop},
                                      'phone': phone, 'store_mode': 'single', 'owner': owner})
    # The form is checked before the code, so fixing a typo costs no guesses.
    if not serializer.is_valid():
        raise serializers.ValidationError(_flatten(serializer.errors))
    check_code(phone, PhoneCode.Purpose.SIGNUP, data.get('code'))

    with transaction.atomic():
        entity = serializer.save()
        user = entity.users.get()
        user.must_change_password = False  # they chose it themselves
        user.language = get_language() if get_language() in ('en', 'sw') else 'en'
        user.save(update_fields=['must_change_password', 'language'])
        if data.get('starter_products'):
            seed_catalog(entity)
    record(Action.SHOP_REGISTERED, Summary('Shop {name} signed itself up', name=entity.name), request=request,
           user=user, entity=entity, data={'owner': user.username, 'self_signup': True,
                                           'starter_products': bool(data.get('starter_products'))})
    return Response({'token': _sign_in(request, user)}, status=201)


def _reset_user(username):
    username = (username or '').strip()
    user = User.objects.filter(username__iexact=username, is_active=True, is_superuser=False).first() if username else None
    if user is None:
        # A self-registered owner may type their number as 0712 345 678.
        try:
            phone = normalize_mobile(username)
        except serializers.ValidationError:
            phone = ''
        if phone:
            user = User.objects.filter(username__iexact=_username_for(phone), is_active=True, is_superuser=False).first()
    if user is None or not user.phone:
        raise serializers.ValidationError({'username': [gettext(
            'We could not send a code for this account. If you work in a shop, ask its owner to reset your password.')]})
    if shop_suspended(user):
        raise exceptions.PermissionDenied(gettext('This shop is suspended. Contact the system administrator.'))
    return user


@public
def password_reset_code(request):
    user = _reset_user(request.data.get('username'))
    reply = send_code(user.phone, PhoneCode.Purpose.PASSWORD_RESET, request=request, user=user)
    return Response({**reply, 'username': user.username})


@public
def password_reset(request):
    user = _reset_user(request.data.get('username'))
    password = request.data.get('new_password') or ''
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({'new_password': list(exc.messages)})
    check_code(user.phone, PhoneCode.Purpose.PASSWORD_RESET, request.data.get('code'), user=user)
    user.set_password(password)
    user.must_change_password = False
    user.save(update_fields=['password', 'must_change_password'])
    revoke_sessions(user)
    record(Action.PASSWORD_CHANGED, Summary('{username} reset their password with an SMS code to {phone}',
                                            username=user.username, phone=masked(user.phone)),
           request=request, user=user)
    return Response({'token': _sign_in(request, user)})
