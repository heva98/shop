import uuid

from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy

from core.models import Entity, Store, User

from .sms_templates import TEMPLATE_KEYS


class NotificationLog(models.Model):
    """Daily sales / daily purchases summaries, computed cloud-side once a
    store's data has synced — see notifications/interfaces.py. Email only
    now: SMS goes through SmsBatch / SmsMessage below."""

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


class SmsLanguage(models.TextChoices):
    SW = 'sw', 'Kiswahili'
    EN = 'en', 'English'


class SmsConfiguration(models.Model):
    """One row per shop (SmsConfiguration.load(entity)). The master on/off
    switch is the sms_notifier module (Settings > Notifications)."""
    entity = models.OneToOneField(Entity, on_delete=models.CASCADE, related_name='sms_configuration')
    language = models.CharField(
        max_length=2, choices=SmsLanguage.choices, blank=True,
        help_text="Blank = each recipient's own app language.",
    )
    daily_sales_to_managers = models.BooleanField(
        default=False, help_text="Also send each store's daily sales summary to that store's managers.",
    )
    # Can only lower the server's SMS_BATCH_RECIPIENT_CAP / SMS_MAX_SEGMENTS.
    batch_recipient_cap = models.PositiveIntegerField(null=True, blank=True)
    max_segments = models.PositiveSmallIntegerField(null=True, blank=True)

    @classmethod
    def load(cls, entity):
        return cls.objects.get_or_create(entity=entity)[0]

    def __str__(self):
        return f'SMS settings for {self.entity}'


class SmsTemplate(models.Model):
    """The text sent for one key in one language; the owner may edit it.
    Missing rows are created from sms_templates.DEFAULT_TEMPLATES."""
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='sms_templates')
    key = models.CharField(max_length=40, choices=TEMPLATE_KEYS)
    language = models.CharField(max_length=2, choices=SmsLanguage.choices)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key', 'language']
        constraints = [models.UniqueConstraint(fields=['entity', 'key', 'language'], name='uniq_sms_template')]

    def __str__(self):
        return f'{self.key} ({self.language})'


class SmsBatch(models.Model):
    """One send: every recipient gets an SmsMessage row, skipped ones too,
    so the log always says why someone did not get a message."""

    class Kind(models.TextChoices):
        DAILY_SALES_SUMMARY = 'DAILY_SALES_SUMMARY', gettext_lazy('Daily sales summary')

    class Status(models.TextChoices):
        PENDING = 'PENDING', gettext_lazy('Pending')
        QUEUED = 'QUEUED', gettext_lazy('Queued')
        RUNNING = 'RUNNING', gettext_lazy('Sending')
        COMPLETED = 'COMPLETED', gettext_lazy('Completed')
        FAILED = 'FAILED', gettext_lazy('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='sms_batches')
    kind = models.CharField(max_length=40, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    sender_id = models.CharField(max_length=64, blank=True)
    dry_run = models.BooleanField(default=False)
    context = models.JSONField(default=dict, blank=True, help_text='Who and what was targeted, for the audit.')
    idempotency_key = models.CharField(max_length=128, blank=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    total_segments = models.PositiveIntegerField(default=0)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['idempotency_key'], condition=~Q(idempotency_key=''), name='uniq_sms_batch_idempotency_key',
        )]

    def __str__(self):
        return f'{self.kind} {self.created_at:%Y-%m-%d} ({self.status})'


class SmsMessage(models.Model):
    """One recipient of a batch: one message per (phone, store), so an
    owner of two stores gets one summary per store, never two for one."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', gettext_lazy('Pending')
        SENT = 'SENT', gettext_lazy('Sent')
        DELIVERED = 'DELIVERED', gettext_lazy('Delivered')
        FAILED = 'FAILED', gettext_lazy('Failed')
        SKIPPED = 'SKIPPED', gettext_lazy('Skipped')

    class SkipReason(models.TextChoices):
        NO_PHONE = 'no_phone', gettext_lazy('No mobile number on file')
        NO_TEMPLATE = 'no_template', gettext_lazy('No active template for this language')
        INVALID_PHONE = 'invalid_phone', gettext_lazy('Not a valid Tanzanian mobile number')
        DUPLICATE = 'duplicate', gettext_lazy('Already in this batch')
        MISSING_VALUE = 'missing_value', gettext_lazy('A template value is missing')
        TOO_LONG = 'too_long', gettext_lazy('Longer than the SMS limit')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(SmsBatch, on_delete=models.CASCADE, related_name='messages')
    store = models.ForeignKey(Store, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    recipient = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    recipient_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=20, blank=True, help_text='+255… form; the raw value when invalid.')
    body = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    skip_reason = models.CharField(max_length=20, choices=SkipReason.choices, blank=True)
    error_detail = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=128, blank=True)
    provider_status = models.CharField(max_length=64, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    segments = models.PositiveSmallIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['recipient_name']
        # Skipped rows are exempt: two owners without a number both get one.
        constraints = [models.UniqueConstraint(
            fields=['batch', 'phone', 'store'], condition=~Q(status='SKIPPED'), name='uniq_sms_message_per_batch',
        )]

    def __str__(self):
        return f'{self.phone} ({self.status})'
