import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from catalog.models import Product, UnitOfMeasure, convert_qty
from core.models import Entity, Store
from inventory.models import StockBatch, StockError, StockLedger


class Supplier(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    payment_terms_days = models.PositiveIntegerField(
        default=0, help_text='Days of credit the supplier gives: 0 = paid on delivery, 30 = due a month after delivery.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ReceivingInvoice(models.Model):
    """Draft -> Received state machine. Draft invoices are resumable;
    receiving posts stock to the ledger and locks the invoice."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        RECEIVED = 'received', 'Received'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='receiving_invoices')
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='invoices')
    invoice_number = models.CharField(max_length=64)
    received_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)
    due_date = models.DateField(
        null=True, blank=True,
        help_text="When payment is due; defaults to the received date plus the supplier's payment terms.",
    )

    class Meta:
        indexes = [models.Index(fields=['store', 'status'])]
        unique_together = [('store', 'invoice_number')]

    def __str__(self):
        return self.invoice_number

    @transaction.atomic
    def mark_received(self):
        """Locks the invoice and posts every line to stock: creates or tops
        up the named batch and writes a Transfer In ledger entry per line,
        referencing this invoice — mirrors how the design's own mock data
        represents a posted receiving invoice."""
        if self.status == self.Status.RECEIVED:
            return
        lines = list(self.lines.select_related('product__uom', 'uom'))
        if not lines:
            raise StockError('Add at least one line before receiving the invoice.')
        missing = [line.product.name for line in lines if line.product.tracks_expiry and not line.expiry_date]
        if missing:
            raise StockError(f'These goods expire, so the expiry date is required for: {", ".join(missing)}.')
        for line in lines:
            # The invoice is in the supplier's unit (e.g. Crate of 24); stock
            # and cost are held in the product's own unit (e.g. Bottle).
            invoice_qty = line.batch_qty if line.batch_qty is not None else line.order_qty
            qty = convert_qty(invoice_qty, line.uom, line.product.uom)
            per_pack = convert_qty(1, line.uom, line.product.uom)
            unit_cost = (line.pack_price / per_pack).quantize(Decimal('0.01')) if per_pack else line.pack_price
            # Goods without a batch number top up the batch with the same
            # expiry (or none), so a shop that doesn't track batches still
            # keeps one batch per expiry date.
            batch_key = {'batch_no': line.batch_no} if line.batch_no else {'batch_no': '', 'expiry_date': line.expiry_date}
            batch, created = StockBatch.objects.get_or_create(
                store=self.store, product=line.product, **batch_key,
                defaults={'expiry_date': line.expiry_date, 'unit_cost': unit_cost},
            )
            if not created and batch.unit_cost == 0:
                batch.unit_cost = unit_cost
                batch.save(update_fields=['unit_cost'])
            StockLedger.record(
                store=self.store, batch=batch, qty_delta=qty,
                ledger_type=StockLedger.LedgerType.TRANSFER_IN,
                ref_type='receiving_invoice', ref_id=self.id,
            )
        self.status = self.Status.RECEIVED
        self.received_at = timezone.now()
        if self.due_date is None:
            self.refresh_from_db(fields=['received_date'])  # may still be the string it was created with
            self.due_date = self.received_date + timedelta(days=self.supplier.payment_terms_days)
        self.save(update_fields=['status', 'received_at', 'due_date'])

    @property
    def total(self):
        return sum((line.order_qty * line.pack_price for line in self.lines.all()), Decimal('0'))

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal('0'))

    @property
    def balance(self):
        return self.total - self.amount_paid

    @transaction.atomic
    def record_payment(self, *, amount, paid_on, method, reference, user):
        locked = ReceivingInvoice.objects.select_for_update().get(pk=self.pk)
        if locked.status != self.Status.RECEIVED:
            raise StockError('Receive the invoice before recording a payment against it.')
        if amount <= 0:
            raise StockError('Payment amount must be above zero.')
        if amount > locked.balance:
            raise StockError(f'That is more than the {locked.balance:,.0f} still owed on this invoice.')
        return SupplierPayment.objects.create(
            invoice=locked, amount=amount, paid_on=paid_on, method=method, reference=reference, recorded_by=user,
        )


class ReceivingInvoiceLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(ReceivingInvoice, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='+')
    uom = models.ForeignKey(UnitOfMeasure, on_delete=models.PROTECT, related_name='+')
    order_qty = models.DecimalField(max_digits=12, decimal_places=2)
    pack_price = models.DecimalField(max_digits=12, decimal_places=2)
    batch_no = models.CharField(max_length=64, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    batch_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f'{self.product} x{self.order_qty}'


class SupplierPayment(models.Model):
    """Money paid to a supplier against a received invoice. An invoice is
    settled when its payments add up to its total; anything left is owed
    (see the Supplier balances report)."""

    class Method(models.TextChoices):
        CASH = 'cash', 'Cash'
        BANK = 'bank', 'Bank transfer'
        MOBILE_MONEY = 'mobile_money', 'Mobile money'
        CHEQUE = 'cheque', 'Cheque'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(ReceivingInvoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=64, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_on', '-created_at']

    def __str__(self):
        return f'{self.amount} to {self.invoice.supplier} ({self.invoice.invoice_number})'
