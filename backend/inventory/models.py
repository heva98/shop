import uuid

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

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


class InsufficientStockError(Exception):
    """A requested stock movement would take a batch below zero, or there
    isn't enough total stock across batches to cover an allocation. Mapped
    to an HTTP 400 by config.exceptions.custom_exception_handler — never
    silently clamped, since that would mean selling stock that isn't
    there."""


class StockError(Exception):
    """A stock operation broke a business rule (receiving a perishable
    line without an expiry date, approving a count twice, ...). Mapped to
    HTTP 400 by config.exceptions.custom_exception_handler."""


def sellable_batches(queryset, on=None):
    """The batches in `queryset` with stock that may be sold or sent on:
    not expired (or never expiring)."""
    on = on or timezone.localdate()
    return queryset.filter(qty_on_hand__gt=0).filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=on))


def fefo_batches(store, product):
    """First-Expired-First-Out ordering for stock movement and selling;
    batches that never expire come last, oldest delivery first. Expired
    batches are never offered: they may not be sold or sent on, only
    written off."""
    return sellable_batches(StockBatch.objects.filter(store=store, product=product)).order_by(
        F('expiry_date').asc(nulls_last=True), 'created_at')


@transaction.atomic
def allocate_fefo(store, product, qty):
    """Picks which batch(es) to deduct `qty` of `product` from at `store`,
    earliest-expiring first, splitting across batches when one isn't
    enough. Returns a list of (batch, qty_from_that_batch) pairs covering
    the full requested quantity. Locks every batch it considers so two
    concurrent allocations can't both plan against the same stock.

    Raises InsufficientStockError if the store doesn't have enough total
    unexpired stock of the product to cover qty, without touching anything.
    """
    remaining = qty
    plan = []
    batches = fefo_batches(store, product).select_for_update()
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.qty_on_hand, remaining)
        plan.append((batch, take))
        remaining -= take
    if remaining > 0:
        raise InsufficientStockError(
            f'Not enough unexpired stock of {product} at {store}: short by {remaining}.',
        )
    return plan


class StockLedger(models.Model):
    """Append-only, kernel table. Every other module (Sale, Transfer,
    ReceivingInvoice, ...) writes here rather than mutating qty_on_hand
    directly — this is the single source of truth for every quantity
    change, and what reports and Analytics read."""

    class LedgerType(models.TextChoices):
        TRANSFER_IN = 'transfer_in', 'Transfer In'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out'
        STOLEN = 'stolen', 'Stolen'
        LOST = 'lost', 'Lost'
        DAMAGED = 'damaged', 'Damaged'
        EXPIRED = 'expired', 'Expired'
        COLD_CHAIN_FAILURE = 'cold_chain_failure', 'Spoiled (fridge / freezer failure)'
        WRONG_ENTRY = 'wrong_entry', 'Wrong Entry'
        SOLD = 'sold', 'Sold'
        SALE_VOID = 'sale_void', 'Sale voided'
        OPENING_STOCK = 'opening_stock', 'Opening stock'
        STOCK_COUNT = 'stock_count', 'Stock count correction'
        DISCARD = 'discard', 'Discard'
        CONSUMPTION = 'consumption', 'Consumption'
        DISPOSE = 'dispose', 'Dispose'

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

    @classmethod
    @transaction.atomic
    def record(cls, *, store, batch, qty_delta, ledger_type, ref_type='', ref_id=''):
        """The only sanctioned way to move stock: locks the batch, writes
        the ledger row, and applies qty_delta to the batch in one
        transaction, so the ledger and qty_on_hand can never drift apart
        and two concurrent calls against the same batch can't both
        succeed past zero. A positive delta (receiving, transfer in) is
        never blocked — only a delta that would take the batch negative is."""
        locked = StockBatch.objects.select_for_update().get(pk=batch.pk)
        new_qty = locked.qty_on_hand + qty_delta
        if new_qty < 0:
            raise InsufficientStockError(
                f'{locked} has {locked.qty_on_hand} on hand; cannot apply {qty_delta}.',
            )
        entry = cls.objects.create(
            store=store, batch=locked, qty_delta=qty_delta, ledger_type=ledger_type,
            ref_type=ref_type, ref_id=str(ref_id),
        )
        locked.qty_on_hand = new_qty
        locked.save(update_fields=['qty_on_hand'])
        batch.qty_on_hand = new_qty
        return entry


class StockAdjustment(models.Model):
    """A recorded reason for stock leaving (or, for a corrected wrong entry,
    returning to) a batch outside sales, receiving and transfers: expiry
    write-offs, breakages, theft, internal use. Manager-only, and every one
    is a ledger entry, so losses show up in reports instead of silently
    shrinking stock."""

    class Reason(models.TextChoices):
        EXPIRED = 'expired', 'Expired'
        DAMAGED = 'damaged', 'Damaged / broken'
        LOST = 'lost', 'Lost'
        STOLEN = 'stolen', 'Stolen'
        COLD_CHAIN_FAILURE = 'cold_chain_failure', 'Spoiled (fridge / freezer failure)'
        CONSUMPTION = 'consumption', 'Internal use'
        DISPOSE = 'dispose', 'Disposed (other)'
        WRONG_ENTRY = 'wrong_entry', 'Correcting a wrong entry'

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

    @classmethod
    @transaction.atomic
    def apply(cls, *, batch, qty_delta, reason, note, user):
        if qty_delta == 0:
            raise StockError('Quantity must not be zero.')
        if qty_delta > 0 and reason != cls.Reason.WRONG_ENTRY:
            raise StockError('Only "Correcting a wrong entry" can add stock; use Receiving for new stock.')
        entry = StockLedger.record(
            store=batch.store, batch=batch, qty_delta=qty_delta, ledger_type=reason, ref_type='stock_adjustment',
        )
        adjustment = cls.objects.create(
            store=batch.store, batch=batch, qty_delta=qty_delta, reason=reason, note=note,
            created_by=user, ledger_entry=entry,
        )
        entry.ref_id = str(adjustment.id)
        entry.save(update_fields=['ref_id'])
        return adjustment


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
        DRAFT = 'draft', 'Counting'
        SUBMITTED = 'submitted', 'Awaiting approval'
        APPROVED = 'approved', 'Approved'
        CANCELLED = 'cancelled', 'Cancelled'

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

    def _require(self, *statuses):
        if self.status not in statuses:
            raise StockError(f'This count is {self.get_status_display().lower()}.')

    @classmethod
    @transaction.atomic
    def start(cls, *, store, user, products=None, note=''):
        """One line per batch the store holds; `products` limits it to a
        partial (cycle) count of just those products."""
        count = cls.objects.create(store=store, created_by=user, note=note)
        batches = StockBatch.objects.filter(store=store, qty_on_hand__gt=0).select_related('product')
        if products:
            batches = batches.filter(product__in=products)
        StockCountLine.objects.bulk_create([
            StockCountLine(count=count, batch=b, product=b.product, batch_no=b.batch_no, expiry_date=b.expiry_date)
            for b in batches.order_by('product__name', F('expiry_date').asc(nulls_last=True))
        ])
        return count

    @transaction.atomic
    def submit(self, *, user):
        self._require(self.Status.DRAFT)
        lines = list(self.lines.select_related('batch'))
        if not lines:
            raise StockError('There is nothing to count.')
        uncounted = sum(1 for line in lines if line.counted_qty is None)
        if uncounted:
            raise StockError(f'{uncounted} line(s) are not counted yet. Enter 0 for anything not on the shelf.')
        for line in lines:
            line.expected_qty = line.batch.qty_on_hand if line.batch_id else 0
        StockCountLine.objects.bulk_update(lines, ['expected_qty'])
        self.status, self.submitted_by, self.submitted_at = self.Status.SUBMITTED, user, timezone.now()
        self.save(update_fields=['status', 'submitted_by', 'submitted_at'])

    @transaction.atomic
    def approve(self, *, user):
        self._require(self.Status.SUBMITTED)
        for line in self.lines.select_related('batch__product', 'product'):
            delta = line.counted_qty - line.expected_qty
            if delta == 0:
                continue
            batch = line.batch
            if batch is None:
                batch = StockBatch.objects.create(
                    store=self.store, product=line.product, batch_no=line.batch_no, expiry_date=line.expiry_date)
                line.batch = batch
            StockLedger.record(
                store=self.store, batch=batch, qty_delta=delta,
                ledger_type=StockLedger.LedgerType.STOCK_COUNT, ref_type='stock_count', ref_id=self.id,
            )
            line.adjustment_qty = delta
            line.save(update_fields=['batch', 'adjustment_qty'])
        self.status, self.approved_by, self.approved_at = self.Status.APPROVED, user, timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at'])

    def reopen(self):
        self._require(self.Status.SUBMITTED)
        self.lines.update(expected_qty=None)
        self.status = self.Status.DRAFT
        self.save(update_fields=['status'])

    def cancel(self):
        self._require(self.Status.DRAFT, self.Status.SUBMITTED)
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status'])


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
