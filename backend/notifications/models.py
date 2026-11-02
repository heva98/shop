import uuid

from django.db import models
from django.utils.translation import gettext_lazy

from core.models import Store


class NotificationLog(models.Model):
    """Daily sales / daily purchases summaries, computed cloud-side once a
    store's data has synced — see notifications/interfaces.py."""

    class Channel(models.TextChoices):
        SMS = 'sms', 'SMS'
        EMAIL = 'email', gettext_lazy('Email')

    class Kind(models.TextChoices):
        DAILY_SALES = 'daily_sales', gettext_lazy('Daily sales summary')
        DAILY_PURCHASES = 'daily_purchases', gettext_lazy('Daily purchases summary')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='notification_logs')
    channel = models.CharField(max_length=10, choices=Channel.choices)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    recipient = models.CharField(max_length=255, blank=True)
    success = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.kind} via {self.channel} to {self.store}'
