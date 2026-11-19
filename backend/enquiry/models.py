import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

from catalog.models import Product
from core.models import Store
from inventory.models import StockBatch
from payments.models import PaymentMethod


class Enquiry(models.Model):
    """mode is stamped from entity.main_store_id at creation time, so a
    later change to entity topology doesn't retroactively alter enquiries
    already in flight."""

    class Mode(models.TextChoices):
        BROADCAST = 'broadcast', gettext_lazy('Broadcast')
        HUB = 'hub', gettext_lazy('Hub')

    class Status(models.TextChoices):
        OPEN = 'open', gettext_lazy('Open')
        FULFILLED = 'fulfilled', gettext_lazy('Fulfilled')
        REJECTED = 'rejected', gettext_lazy('Rejected')
        CANCELLED = 'cancelled', gettext_lazy('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requesting_store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='enquiries_made')
    mode = models.CharField(max_length=10, choices=Mode.choices)
    target_store = models.ForeignKey(
        Store, null=True, blank=True, on_delete=models.SET_NULL, related_name='enquiries_targeted',
        help_text='Hub mode only — the entity main store',
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Enquiry {self.id} ({self.status})'


class EnquiryLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='+')
    qty_requested = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f'{self.product} x{self.qty_requested}'


class Transfer(models.Model):
    """Single object for all inter-store movement. Mode is decided by the
    firm's set-up when the transfer is sent: stock leaving the main store
    of a hub firm is `hub` (the branch is billed for it at cost, and the
    main store records the branch's payment); everything else is `peer`
    (no money changes hands).

    Lifecycle: dispatched (stock has left the sender, in transit) ->
    received (everything arrived) | discrepancy (less arrived than was
    sent; the shortfall is resolved by returning it to the sender, adding
    it to the receiver when it turns up, or writing it off as lost) ->
    received. A dispatched transfer can also be cancelled by the sender,
    which puts the stock back. Every movement is a StockLedger entry
    referencing the transfer. The transitions: enquiry.services.transfers."""

    class Mode(models.TextChoices):
        PEER = 'peer', gettext_lazy('Peer')
        HUB = 'hub', gettext_lazy('Hub')

    class Status(models.TextChoices):
        DISPATCHED = 'dispatched', gettext_lazy('In transit')
        RECEIVED = 'received', gettext_lazy('Received')
        DISCREPANCY = 'discrepancy', gettext_lazy('Short delivery')
        CANCELLED = 'cancelled', gettext_lazy('Cancelled')

    class Resolution(models.TextChoices):
        RETURN_TO_SENDER = 'return_to_sender', gettext_lazy('Back in stock at the sending store')
        RECEIVED_LATE = 'received_late', gettext_lazy('Found, added to the receiving store')
        WRITE_OFF = 'write_off', gettext_lazy('Lost in transit, written off')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.PositiveIntegerField(null=True, blank=True, help_text='Sequential per firm, for the delivery note.')
    enquiry = models.ForeignKey(Enquiry, null=True, blank=True, on_delete=models.SET_NULL, related_name='transfers')
    from_store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='transfers_out')
    to_store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='transfers_in')
    mode = models.CharField(max_length=10, choices=Mode.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DISPATCHED)
    note = models.CharField(max_length=255, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    discrepancy_note = models.TextField(blank=True)
    resolution = models.CharField(max_length=20, choices=Resolution.choices, blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Hub mode: what the branch owes, at cost, for what it received.')
    payment_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text='Hub mode: how the branch paid.',
    )
    payment_reference = models.CharField(max_length=64, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-dispatched_at']

    def __str__(self):
        return f'Transfer {self.number or self.id} {self.from_store} -> {self.to_store}'

    @property
    def is_billed(self):
        return self.mode == self.Mode.HUB

    @property
    def balance(self):
        if not self.is_billed or self.paid_at or not self.amount or self.status != self.Status.RECEIVED:
            return Decimal('0')
        return self.amount



class TransferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name='lines')
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name='+', help_text="The sender's batch.")
    qty = models.DecimalField(max_digits=12, decimal_places=2, help_text="Sent, in the product's own unit.")
    received_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Cost per unit when sent.')

    def __str__(self):
        return f'{self.batch} x{self.qty}'
