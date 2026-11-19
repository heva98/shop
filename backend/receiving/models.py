import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Store


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
    receiving (receiving.services.receive) posts stock to the ledger and
    locks the invoice."""

    class Status(models.TextChoices):
        DRAFT = 'draft', gettext_lazy('Draft')
        RECEIVED = 'received', gettext_lazy('Received')

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

    @property
    def total(self):
        return sum((line.order_qty * line.pack_price for line in self.lines.all()), Decimal('0'))

    @property
    def amount_paid(self):
        return sum((p.amount for p in self.payments.all()), Decimal('0'))

    @property
    def balance(self):
        return self.total - self.amount_paid



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
        CASH = 'cash', gettext_lazy('Cash')
        BANK = 'bank', gettext_lazy('Bank transfer')
        MOBILE_MONEY = 'mobile_money', gettext_lazy('Mobile money')
        CHEQUE = 'cheque', gettext_lazy('Cheque')

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
