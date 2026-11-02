from django.conf import settings
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from audit.services import Action, Summary, record
from core.models import ModuleEnablement, ModuleRegistry, Role
from core.permissions import roles
from core.phone import is_tz_mobile, normalize_tz_phone
from core.queryset_scoping import TenantScopedQuerySetMixin

from .channels.email_channel import EmailChannel
from .models import NotificationLog, SmsBatch, SmsConfiguration, SmsMessage, SmsTemplate
from .modules import MODULE_KEY_BY_CHANNEL
from .serializers import (
    NotificationLogSerializer, SmsBatchDetailSerializer, SmsBatchSerializer, SmsConfigurationSerializer,
    SmsSendSerializer, SmsTemplateSerializer,
)
from .sms_audiences import daily_sales_recipients
from .sms_backends import get_sms_backend
from .sms_jobs import run_sms_batch
from .sms_service import BatchTooLarge, create_batch, ensure_templates, limits, preview_recipients, requeue_failed
from .sms_templates import TemplateSyntaxError

# The owner (entity admin) runs the shop's SMS: settings, texts, sends and the log.
OwnerOnly = roles(Role.ENTITY_ADMIN)


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


def _entity(request):
    entity = request.user.entity
    if entity is None:
        raise ValidationError(gettext('Your account is not linked to a shop.'))
    return entity


def sms_server_state():
    backend = get_sms_backend()
    return {
        'sms_backend': backend.name,
        # True only when messages really leave the server.
        'sms_configured': backend.sends and backend.configured,
        'sms_price_per_segment': settings.SMS_PRICE_PER_SEGMENT,
    }


def _channel_state(entity):
    state = {}
    for channel, key in MODULE_KEY_BY_CHANNEL.items():
        state[f'{channel}_enabled'] = ModuleEnablement.objects.filter(
            module__key=key, entity=entity, store__isnull=True, enabled=True).exists()
    state['email_configured'] = EmailChannel().configured
    state.update(sms_server_state())
    return state


@api_view(['GET', 'PATCH'])
@permission_classes([OwnerOnly])
def notification_settings(request):
    """GET the firm's end-of-day summary switches (and whether email/SMS
    are actually configured on the server); PATCH {email_enabled,
    sms_enabled} to switch them."""
    entity = _entity(request)
    if request.method == 'PATCH':
        for channel, key in MODULE_KEY_BY_CHANNEL.items():
            field = f'{channel}_enabled'
            if field in request.data:
                on = str(request.data[field]).lower() in ('true', '1', 'yes')
                module = ModuleRegistry.objects.get(key=key)
                ModuleEnablement.objects.update_or_create(
                    module=module, entity=entity, store=None, defaults={'enabled': on})
                record(Action.SETTINGS_CHANGED, Summary('Daily summary by {channel} switched {value}', channel=channel, value="on" if on else "off"),
                       request=request, entity=entity)
    return Response(_channel_state(entity))


@api_view(['POST'])
@permission_classes([roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)])
def test_sms(request):
    """Sends a test message to the caller's own phone number, to check the
    SMS set-up end to end."""
    user = request.user
    phone = normalize_tz_phone(user.phone)
    if not user.phone:
        raise ValidationError(gettext('Add your mobile number under "Edit my details" first.'))
    if not is_tz_mobile(phone):
        raise ValidationError(gettext('{phone} is not a Tanzanian mobile number.').format(phone=user.phone))
    backend = get_sms_backend()
    if not (backend.sends and backend.configured):
        raise ValidationError(gettext('SMS is not configured on the server. Set SMS_BACKEND and the provider keys in .env.'))
    result = backend.send_one(phone, gettext('Test message from {name}. SMS is working.').format(
        name=user.entity.name if user.entity else 'Shop ERP'), backend.default_sender_id())
    if not result.ok:
        raise ValidationError(gettext('The SMS provider refused the message: {error}').format(error=result.error))
    return Response({'detail': gettext('Test SMS sent to {phone}.').format(phone=phone)})


@api_view(['GET', 'PATCH'])
@permission_classes([OwnerOnly])
def sms_config(request):
    entity = _entity(request)
    config = SmsConfiguration.load(entity)
    if request.method == 'PATCH':
        serializer = SmsConfigurationSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(Action.SETTINGS_CHANGED, Summary('SMS settings changed'), request=request, entity=entity)
    cap, max_segments = limits(config)
    return Response({
        **SmsConfigurationSerializer(config).data,
        'effective_recipient_cap': cap, 'effective_max_segments': max_segments,
        **sms_server_state(),
    })


class SmsTemplateViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """GET sms/templates/?language=sw; PATCH sms/templates/{id}/ {body, is_active}."""
    serializer_class = SmsTemplateSerializer
    permission_classes = [OwnerOnly]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_queryset(self):
        entity = _entity(self.request)
        ensure_templates(entity)
        qs = SmsTemplate.objects.filter(entity=entity)
        language = self.request.query_params.get('language')
        return qs.filter(language=language.lower()) if language else qs

    def perform_update(self, serializer):
        template = serializer.save()
        record(Action.SETTINGS_CHANGED, Summary('SMS template {key} ({language}) changed',
                                                key=template.key, language=template.language),
               request=self.request, entity=template.entity)


def _recipients(request, data):
    """Recipients for a preview/send body; only the daily sales summary for now."""
    day = data.get('date') or timezone.localdate()
    if day > timezone.localdate():
        raise ValidationError({'date': gettext('Pick today or an earlier day.')})
    recipients = daily_sales_recipients(_entity(request), day, language=data.get('language'))
    if not recipients:
        raise ValidationError(gettext('Nobody to send to: switch SMS on and add an owner with a mobile number.'))
    return day, recipients


@api_view(['POST'])
@permission_classes([OwnerOnly])
def sms_preview(request):
    serializer = SmsSendSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    _day, recipients = _recipients(request, serializer.validated_data)
    try:
        return Response(preview_recipients(_entity(request), recipients))
    except TemplateSyntaxError as exc:
        raise ValidationError(gettext('The SMS template has an error: {error}').format(error=exc)) from exc


@api_view(['POST'])
@permission_classes([OwnerOnly])
def sms_send(request):
    """Sends the summary now (or saves it without sending, with dry_run).
    Owner batches are a handful of messages, so they go out within the
    request; the nightly run uses the same create_batch/send_batch."""
    serializer = SmsSendSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    day, recipients = _recipients(request, data)
    try:
        batch = create_batch(
            _entity(request), data['kind'], recipients, dry_run=data['dry_run'], created_by=request.user,
            context={'date': day.isoformat(), 'audience': 'owners', 'trigger': 'manual',
                     'stores': sorted({r.store.name for r in recipients})},
        )
    except (TemplateSyntaxError, BatchTooLarge) as exc:
        raise ValidationError(str(exc)) from exc
    if batch.status == SmsBatch.Status.QUEUED:
        batch = run_sms_batch(batch.pk)
    return Response(SmsBatchDetailSerializer(batch).data, status=201)


class SmsBatchViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """The SMS delivery log: GET sms/batches/?kind=&status=&date_from=&date_to=."""
    queryset = SmsBatch.objects.select_related('created_by')
    entity_field = 'entity_id'
    permission_classes = [OwnerOnly]
    filterset_fields = ['kind', 'status']

    def get_serializer_class(self):
        return SmsBatchDetailSerializer if self.action != 'list' else SmsBatchSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params
        if params.get('date_from'):
            qs = qs.filter(created_at__date__gte=params['date_from'])
        if params.get('date_to'):
            qs = qs.filter(created_at__date__lte=params['date_to'])
        if self.action != 'list':
            qs = qs.prefetch_related(Prefetch('messages', SmsMessage.objects.select_related('store')))
        return qs

    @action(detail=True, methods=['post'], url_path='resend-failed')
    def resend_failed(self, request, pk=None):
        batch = get_object_or_404(self.get_queryset(), pk=pk)
        if not requeue_failed(batch):
            raise ValidationError(gettext('No failed messages to resend.'))
        batch = run_sms_batch(batch.pk)
        return Response(SmsBatchDetailSerializer(batch).data)
