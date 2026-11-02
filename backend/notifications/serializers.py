from django.utils.translation import gettext
from rest_framework import serializers

from .models import NotificationLog, SmsBatch, SmsConfiguration, SmsMessage, SmsTemplate
from .sms_segments import count_segments
from .sms_templates import PLACEHOLDERS, TemplateSyntaxError, check_template


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = ['id', 'store', 'channel', 'kind', 'recipient', 'success', 'error', 'sent_at']
        read_only_fields = fields


class SmsConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SmsConfiguration
        fields = ['language', 'daily_sales_to_managers', 'batch_recipient_cap', 'max_segments']


class SmsTemplateSerializer(serializers.ModelSerializer):
    placeholders = serializers.SerializerMethodField()
    segments = serializers.SerializerMethodField()

    class Meta:
        model = SmsTemplate
        fields = ['id', 'key', 'language', 'body', 'is_active', 'updated_at', 'placeholders', 'segments']
        read_only_fields = ['id', 'key', 'language', 'updated_at']

    def get_placeholders(self, obj):
        return list(PLACEHOLDERS.get(obj.key, {}))

    def get_segments(self, obj):
        return count_segments(obj.body)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError(gettext('The message cannot be empty.'))
        try:
            check_template(value, self.instance.key)
        except TemplateSyntaxError as exc:
            raise serializers.ValidationError(
                gettext('The SMS template has an error: {error}').format(error=exc)) from exc
        return value


class SmsMessageSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', default='', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    skip_reason_label = serializers.CharField(source='get_skip_reason_display', read_only=True)

    class Meta:
        model = SmsMessage
        fields = ['id', 'store', 'store_name', 'recipient', 'recipient_name', 'phone', 'body', 'status',
                  'status_label', 'skip_reason', 'skip_reason_label', 'error_detail', 'provider_message_id',
                  'provider_status', 'segments', 'cost', 'sent_at']
        read_only_fields = fields


class SmsBatchSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SmsBatch
        fields = ['id', 'kind', 'kind_label', 'status', 'status_label', 'dry_run', 'context', 'sender_id',
                  'sent_count', 'failed_count', 'skipped_count', 'total_segments', 'total_cost',
                  'created_by_name', 'created_at', 'completed_at']
        read_only_fields = fields

    def get_created_by_name(self, obj):
        user = obj.created_by
        return (user.get_full_name() or user.username) if user else ''


class SmsBatchDetailSerializer(SmsBatchSerializer):
    messages = SmsMessageSerializer(many=True, read_only=True)

    class Meta(SmsBatchSerializer.Meta):
        fields = [*SmsBatchSerializer.Meta.fields, 'messages']
        read_only_fields = fields


class SmsSendSerializer(serializers.Serializer):
    """Body of sms/preview/ and sms/send/."""
    kind = serializers.ChoiceField(choices=SmsBatch.Kind.choices)
    date = serializers.DateField(required=False)
    language = serializers.ChoiceField(choices=['sw', 'en'], required=False)
    dry_run = serializers.BooleanField(default=False)
