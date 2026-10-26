from rest_framework import serializers

from .models import NotificationLog


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = ['id', 'store', 'channel', 'kind', 'recipient', 'success', 'error', 'sent_at']
        read_only_fields = fields
