from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from audit.services import Action, record
from core.models import ModuleEnablement, ModuleRegistry, Role
from core.permissions import roles
from core.queryset_scoping import TenantScopedQuerySetMixin

from .channels.email_channel import EmailChannel
from .channels.sms_channel import SMSChannel, SMSError
from .management.commands.send_daily_summaries import MODULE_KEY_BY_CHANNEL
from .models import NotificationLog
from .serializers import NotificationLogSerializer


class NotificationLogViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only: notifications are fired by the cloud-side daily summary
    job (see notifications/interfaces.py), never posted directly by a
    client. Reporting-adjacent, so gated the same as Analytics (NAV_DEFS
    in appData.js) rather than left open to every store role."""
    queryset = NotificationLog.objects.select_related('store').all()
    serializer_class = NotificationLogSerializer
    filterset_fields = ['store', 'channel', 'kind']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)]


def _channel_state(entity):
    state = {}
    for channel, key in MODULE_KEY_BY_CHANNEL.items():
        state[f'{channel}_enabled'] = ModuleEnablement.objects.filter(
            module__key=key, entity=entity, store__isnull=True, enabled=True).exists()
    state['email_configured'] = EmailChannel().configured
    state['sms_configured'] = SMSChannel().configured
    return state


@api_view(['GET', 'PATCH'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def notification_settings(request):
    """GET the firm's end-of-day summary switches (and whether email/SMS
    are actually configured on the server); PATCH {email_enabled,
    sms_enabled} to switch them."""
    entity = request.user.entity
    if entity is None:
        raise ValidationError('Your account is not linked to a shop.')
    if request.method == 'PATCH':
        for channel, key in MODULE_KEY_BY_CHANNEL.items():
            field = f'{channel}_enabled'
            if field in request.data:
                on = str(request.data[field]).lower() in ('true', '1', 'yes')
                module = ModuleRegistry.objects.get(key=key)
                ModuleEnablement.objects.update_or_create(
                    module=module, entity=entity, store=None, defaults={'enabled': on})
                record(Action.SETTINGS_CHANGED, f'Daily summary by {channel} switched {"on" if on else "off"}',
                       request=request, entity=entity)
    return Response(_channel_state(entity))


@api_view(['POST'])
@permission_classes([roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)])
def test_sms(request):
    """Sends a test message to the caller's own phone number, to check the
    SMS set-up end to end."""
    user = request.user
    if not user.phone:
        raise ValidationError('Add your mobile number under "Edit my details" first.')
    channel = SMSChannel()
    if not channel.configured:
        raise ValidationError('SMS is not configured on the server. Set SMS_PROVIDER and the Beem keys in .env.')
    try:
        channel.send(user.phone, '', f'Test message from {user.entity.name if user.entity else "Shop ERP"}. SMS is working.')
    except SMSError as exc:
        raise ValidationError(str(exc))
    return Response({'detail': f'Test SMS sent to {user.phone}.'})
