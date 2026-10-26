import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class SyncOutbox(models.Model):
    """Outbox pattern, store <-> cloud only (single till per store, no
    in-store LAN sync needed). Every local write on a syncable model also
    inserts a row here; a background process pushes pending rows to the
    cloud whenever connectivity is available.

    All primary keys on syncable models are client-generated UUIDs, so two
    stores (or a store and the cloud) never collide when merging.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SYNCED = 'synced', 'Synced'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store_id = models.UUIDField()
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f'{self.content_type} {self.object_id} ({self.status})'
