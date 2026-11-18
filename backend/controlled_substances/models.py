import uuid

from django.conf import settings
from django.db import models

from catalog.models import Product
from core.models import Store
from inventory.models import StockLedger


class ControlledSubstanceEntry(models.Model):
    """Pharmacies: the controlled drugs register. One row per controlled
    medicine leaving (or, when a sale is voided, coming back to) a store,
    tied to the stock ledger entry that moved it, with who it was dispensed
    to, on whose prescription and by whom. Written only by pos.Sale; never
    edited. Kept apart from general stock reports for inspection."""

    class Kind(models.TextChoices):
        DISPENSED = 'dispensed', 'Dispensed'
        RETURNED = 'returned', 'Returned (sale voided)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='controlled_substance_entries')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='controlled_substance_entries')
    ledger_entry = models.OneToOneField(StockLedger, on_delete=models.PROTECT, related_name='controlled_substance_entry')
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DISPENSED)
    qty = models.DecimalField(max_digits=12, decimal_places=2, help_text="In the product's stock unit; negative = returned.")
    batch_no = models.CharField(max_length=64, blank=True)
    sale = models.ForeignKey('pos.Sale', null=True, blank=True, on_delete=models.PROTECT, related_name='controlled_entries')
    patient_name = models.CharField(max_length=255, blank=True)
    prescriber_name = models.CharField(max_length=255, blank=True)
    prescription_ref = models.CharField(max_length=64, blank=True)
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name='+')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.product} x{self.qty} @ {self.store}'
