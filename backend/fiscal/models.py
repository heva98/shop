import uuid

from django.db import models


class FiscalReceipt(models.Model):
    """Audit/retry log for every fiscalization attempt — a sale can have
    multiple rows here if the first submission failed and was retried,
    which is what the POS's failed/retry UI state is backed by."""

    class Status(models.TextChoices):
        SUBMITTED = 'submitted', 'Submitted'
        FAILED = 'failed', 'Failed'
        RECORDED = 'recorded', 'Entered by cashier'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale_id = models.UUIDField()
    driver = models.CharField(max_length=32, default='manual_efd')
    receipt_number = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.TextField(blank=True)
    entered_by = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text='Who typed the receipt number in, for manually recorded EFD receipts.',
    )
    attempted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.driver} receipt for sale {self.sale_id} ({self.status})'
