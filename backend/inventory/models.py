import uuid

from django.conf import settings
from django.db import models
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext_lazy

from catalog.models import Product
from core.models import Store


class StoreProduct(models.Model):
    """Per-store config for an entity-wide Product: whether this store
    stocks it at all, and the level at which it should be re-ordered."""
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='store_products')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='store_products')
    enabled = models.BooleanField(default=True)
    reorder_level = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        unique_together = [('store', 'product')]

    def __str__(self):
        return f'{self.product} @ {self.store}'


class StockBatch(models.Model):
    """One lot of a product at a store. Goods that don't expire (see
    Product.tracks_expiry) have no expiry date, and often no batch number
    either: their stock simply sits in one batch per delivery."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='batches')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='batches')
    batch_no = models.CharField(max_length=64, blank=True)
    expiry_date = models.DateField(null=True, blank=True, help_text='Empty = does not expire.')
    qty_on_hand = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [F('expiry_date').asc(nulls_last=True), 'created_at']
        indexes = [models.Index(fields=['store', 'product', 'expiry_date'])]

    def __str__(self):
        label = f' #{self.batch_no}' if self.batch_no else ''
        return f'{self.product}{label} @ {self.store}'

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < timezone.localdate()


class StockLedger(models.Model):
    """Append-only, kernel table. Every other module (Sale, Transfer,
    ReceivingInvoice, ...) writes here, through inventory.stock.record_movement,
    rather than mutating qty_on_hand directly — this is the single source
    of truth for every quantity change, and what reports and Analytics read."""

    class LedgerType(models.TextChoices):
        TRANSFER_IN = 'transfer_in', gettext_lazy('Transfer In')
        TRANSFER_OUT = 'transfer_out', gettext_lazy('Transfer Out')
        STOLEN = 'stolen', gettext_lazy('Stolen')
        LOST = 'lost', gettext_lazy('Lost')
        DAMAGED = 'damaged', gettext_lazy('Damaged')
        EXPIRED = 'expired', gettext_lazy('Expired')
        COLD_CHAIN_FAILURE = 'cold_chain_failure', gettext_lazy('Spoiled (fridge / freezer failure)')
        WRONG_ENTRY = 'wrong_entry', gettext_lazy('Wrong Entry')
        SOLD = 'sold', gettext_lazy('Sold')
        SALE_VOID = 'sale_void', gettext_lazy('Sale voided')
        OPENING_STOCK = 'opening_stock', gettext_lazy('Opening stock')
        STOCK_COUNT = 'stock_count', gettext_lazy('Stock count correction')
        DISCARD = 'discard', gettext_lazy('Discard')
        CONSUMPTION = 'consumption', gettext_lazy('Consumption')
        DISPOSE = 'dispose', gettext_lazy('Dispose')
        # Units an offline sale sold that the system had no record of: put
        # on the batch just before the 'sold' entry takes them off, so stock
        # never goes negative and the gap in the records is visible.
        UNRECORDED = 'unrecorded', gettext_lazy('Sold without recorded stock')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='ledger_entries')
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name='ledger_entries')
    qty_delta = models.DecimalField(max_digits=12, decimal_places=2)
    ledger_type = models.CharField(max_length=20, choices=LedgerType.choices)
    ref_type = models.CharField(max_length=32, blank=True, help_text='e.g. "sale", "transfer", "receiving_invoice"')
    ref_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['store', 'created_at']),
            models.Index(fields=['ref_type', 'ref_id']),
        ]

    def __str__(self):
        return f'{self.ledger_type} {self.qty_delta} {self.batch}'



class StockAdjustment(models.Model):
    """A recorded reason for stock leaving (or, for a corrected wrong entry,
    returning to) a batch outside sales, receiving and transfers: expiry
    write-offs, breakages, theft, internal use. Manager-only, and every one
    is a ledger entry, so losses show up in reports instead of silently
    shrinking stock."""

    class Reason(models.TextChoices):
        EXPIRED = 'expired', gettext_lazy('Expired')
        DAMAGED = 'damaged', gettext_lazy('Damaged / broken')
        LOST = 'lost', gettext_lazy('Lost')
        STOLEN = 'stolen', gettext_lazy('Stolen')
        COLD_CHAIN_FAILURE = 'cold_chain_failure', gettext_lazy('Spoiled (fridge / freezer failure)')
        CONSUMPTION = 'consumption', gettext_lazy('Internal use')
        DISPOSE = 'dispose', 'Disposed (other)'
        WRONG_ENTRY = 'wrong_entry', gettext_lazy('Correcting a wrong entry')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='stock_adjustments')
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name='adjustments')
    qty_delta = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=20, choices=Reason.choices, help_text='Doubles as the ledger type.')
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    ledger_entry = models.OneToOneField(StockLedger, on_delete=models.PROTECT, related_name='adjustment')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_reason_display()} {self.qty_delta} {self.batch}'



class StockCount(models.Model):
    """A physical stock take. Staff count every batch on the shelf without
    seeing what the system expects (a blind count, so they really count
    instead of confirming numbers); a manager then sees the differences
    and approves, which writes one 'stock_count' ledger correction per
    batch that differs.

    Count while the till is closed: the expected quantity is taken when
    the count is submitted, so sales between counting and submitting
    would show up as false shortages."""

    class Status(models.TextChoices):
        DRAFT = 'draft', gettext_lazy('Counting')
        SUBMITTED = 'submitted', gettext_lazy('Awaiting approval')
        APPROVED = 'approved', gettext_lazy('Approved')
        CANCELLED = 'cancelled', gettext_lazy('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='stock_counts')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Stock count {self.created_at:%Y-%m-%d} @ {self.store}'



class StockCountLine(models.Model):
    """`batch` is null for stock found on the shelf that the system has no
    batch for; approving the count creates it."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name='lines')
    batch = models.ForeignKey(StockBatch, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='+')
    batch_no = models.CharField(max_length=64, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    expected_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    adjustment_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['product__name', F('expiry_date').asc(nulls_last=True)]

    @property
    def difference(self):
        if self.expected_qty is None or self.counted_qty is None:
            return None
        return self.counted_qty - self.expected_qty
