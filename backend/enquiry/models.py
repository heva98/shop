import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone

from catalog.models import Product
from core import features
from core.models import Entity, Store
from inventory.models import StockBatch, StockError, StockLedger, allocate_fefo
from payments.models import PaymentMethod


class Enquiry(models.Model):
    """mode is stamped from entity.main_store_id at creation time, so a
    later change to entity topology doesn't retroactively alter enquiries
    already in flight."""

    class Mode(models.TextChoices):
        BROADCAST = 'broadcast', 'Broadcast'
        HUB = 'hub', 'Hub'

    class Status(models.TextChoices):
        OPEN = 'open', 'Open'
        FULFILLED = 'fulfilled', 'Fulfilled'
        REJECTED = 'rejected', 'Rejected'
        CANCELLED = 'cancelled', 'Cancelled'

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
    referencing the transfer."""

    class Mode(models.TextChoices):
        PEER = 'peer', 'Peer'
        HUB = 'hub', 'Hub'

    class Status(models.TextChoices):
        DISPATCHED = 'dispatched', 'In transit'
        RECEIVED = 'received', 'Received'
        DISCREPANCY = 'discrepancy', 'Short delivery'
        CANCELLED = 'cancelled', 'Cancelled'

    class Resolution(models.TextChoices):
        RETURN_TO_SENDER = 'return_to_sender', 'Back in stock at the sending store'
        RECEIVED_LATE = 'received_late', 'Found, added to the receiving store'
        WRITE_OFF = 'write_off', 'Lost in transit, written off'

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

    def _require_status(self, *statuses):
        if self.status not in statuses:
            raise StockError(f'This transfer is {self.get_status_display().lower()}.')

    def _post(self, store, batch, qty, ledger_type):
        return StockLedger.record(
            store=store, batch=batch, qty_delta=qty, ledger_type=ledger_type,
            ref_type='transfer', ref_id=self.id,
        )

    def _receiving_batch(self, line):
        """The receiving store's batch matching the one sent: same batch
        number, or for goods without one, the same expiry date."""
        sent = line.batch
        key = {'batch_no': sent.batch_no} if sent.batch_no else {'batch_no': '', 'expiry_date': sent.expiry_date}
        batch, _ = StockBatch.objects.get_or_create(
            store=self.to_store, product=sent.product, **key,
            defaults={'expiry_date': sent.expiry_date, 'unit_cost': line.unit_cost or sent.unit_cost},
        )
        return batch

    def _rebill(self):
        """A hub branch pays for what it actually got."""
        if self.is_billed:
            self.amount = sum(
                ((line.qty if line.received_qty is None else line.received_qty) * line.unit_cost
                 for line in self.lines.all()),
                Decimal('0'),
            ).quantize(Decimal('0.01'))

    @classmethod
    @transaction.atomic
    def send(cls, *, from_store, to_store, items, user=None, enquiry=None, note=''):
        """Creates and dispatches a transfer. `items` is a list of
        {'product': Product, 'qty': n} (batches picked earliest-expiry
        first, so expired stock is never sent) or {'batch': StockBatch,
        'qty': n} (that batch exactly). Quantities are in the product's own
        unit."""
        if from_store.id == to_store.id:
            raise StockError('Choose a different store to send to.')
        if from_store.entity_id != to_store.entity_id:
            raise StockError('Stock can only move between stores of the same shop.')
        if not to_store.is_active:
            raise StockError(f'{to_store.name} is deactivated.')
        features.require('transfer', entity=from_store.entity_id)
        if not items:
            raise StockError('Add at least one product to send.')

        # The entity row lock serializes numbering across the firm.
        entity = Entity.objects.select_for_update().get(pk=from_store.entity_id)
        last = cls.objects.filter(from_store__entity=entity).aggregate(n=Max('number'))['n'] or 0
        transfer = cls.objects.create(
            number=last + 1, enquiry=enquiry, from_store=from_store, to_store=to_store,
            mode=cls.Mode.HUB if entity.main_store_id == from_store.id else cls.Mode.PEER,
            note=(note or '').strip()[:255], dispatched_by=user,
        )
        for item in items:
            try:
                qty = Decimal(str(item['qty']))
            except (InvalidOperation, KeyError):
                raise StockError('Every line needs a quantity.')
            if qty <= 0:
                raise StockError('Quantities must be more than zero.')
            batch = item.get('batch')
            if batch is not None:
                if batch.store_id != from_store.id:
                    raise StockError(f'Batch {batch.batch_no} is not at {from_store.name}.')
                if batch.is_expired:
                    raise StockError(f'Batch {batch.batch_no} has expired and cannot be sent.')
                plan = [(StockBatch.objects.select_for_update().get(pk=batch.pk), qty)]
            else:
                product = item['product']
                if product.entity_id != entity.id:
                    raise StockError("Product is not in this shop's catalog.")
                plan = allocate_fefo(from_store, product, qty)
            for plan_batch, plan_qty in plan:
                TransferLine.objects.create(transfer=transfer, batch=plan_batch, qty=plan_qty, unit_cost=plan_batch.unit_cost)
                transfer._post(from_store, plan_batch, -plan_qty, StockLedger.LedgerType.TRANSFER_OUT)
        if transfer.is_billed:
            transfer._rebill()
            transfer.save(update_fields=['amount'])
        return transfer

    @transaction.atomic
    def confirm_receipt(self, *, user=None, received_qty_by_line: dict = None, note=''):
        """The receiving store counts what arrived. Lines missing from
        received_qty_by_line (line id -> qty) arrived in full. Less than
        was sent on any line flags a short delivery (a note is required)
        until a manager resolves it; more than was sent is refused."""
        locked = Transfer.objects.select_for_update().get(pk=self.pk)
        locked._require_status(self.Status.DISPATCHED)
        received = {str(k): v for k, v in (received_qty_by_line or {}).items()}
        note = (note or '').strip()
        lines = list(locked.lines.select_related('batch__product'))
        counted = []
        for line in lines:
            try:
                qty = Decimal(str(received.get(str(line.id), line.qty)))
            except InvalidOperation:
                raise StockError('Received quantities must be numbers.')
            if qty < 0:
                raise StockError('Received quantities cannot be negative.')
            if qty > line.qty:
                raise StockError(f'{line.batch.product.name}: {qty} received but only {line.qty} were sent. Count again.')
            counted.append((line, qty))
        short = any(qty < line.qty for line, qty in counted)
        if short and not note:
            raise StockError('Less arrived than was sent: add a note saying what is missing.')

        for line, qty in counted:
            if qty > 0:
                locked._post(locked.to_store, locked._receiving_batch(line), qty,
                             StockLedger.LedgerType.TRANSFER_IN)
            line.received_qty = qty
            line.save(update_fields=['received_qty'])
        locked.status = self.Status.DISCREPANCY if short else self.Status.RECEIVED
        locked.discrepancy_note = note if short else ''
        locked.received_by = user
        locked.received_at = timezone.now()
        locked._rebill()
        locked.save(update_fields=['status', 'discrepancy_note', 'received_by', 'received_at', 'amount'])
        self.refresh_from_db()

    @transaction.atomic
    def resolve(self, *, resolution, user=None, note=''):
        """Settles a short delivery. return_to_sender: the missing units
        never left (or came back), so they go back into the sender's batch.
        received_late: they turned up at the receiver, so they're added
        there (and billed). write_off: lost on the way, booked as a loss at
        the sending store so it shows in the losses report."""
        locked = Transfer.objects.select_for_update().get(pk=self.pk)
        locked._require_status(self.Status.DISCREPANCY)
        if resolution not in self.Resolution.values:
            raise StockError('Choose what happened to the missing stock.')
        ref = f'transfer #{locked.number}'
        for line in locked.lines.select_related('batch__product'):
            missing = line.qty - (line.received_qty or 0)
            if missing <= 0:
                continue
            if resolution == self.Resolution.RECEIVED_LATE:
                locked._post(locked.to_store, locked._receiving_batch(line), missing,
                             StockLedger.LedgerType.TRANSFER_IN)
                line.received_qty = line.qty
                line.save(update_fields=['received_qty'])
                continue
            locked._post(locked.from_store, line.batch, missing, StockLedger.LedgerType.TRANSFER_IN)
            if resolution == self.Resolution.WRITE_OFF:
                locked._post(locked.from_store, line.batch, -missing, StockLedger.LedgerType.LOST)
        note = (note or '').strip()
        locked.status = self.Status.RECEIVED
        locked.resolution = resolution
        locked.discrepancy_note = '\n'.join(filter(None, [
            locked.discrepancy_note, f'Resolved: {self.Resolution(resolution).label}' + (f' — {note}' if note else ''),
        ]))
        locked._rebill()
        locked.save(update_fields=['status', 'resolution', 'discrepancy_note', 'amount'])
        self.refresh_from_db()

    @transaction.atomic
    def cancel(self, *, user=None, reason=''):
        """The sender calls a transfer back before it is received: every
        line goes back into the batch it came from."""
        locked = Transfer.objects.select_for_update().get(pk=self.pk)
        locked._require_status(self.Status.DISPATCHED)
        reason = (reason or '').strip()
        if not reason:
            raise StockError('Give a reason for cancelling this transfer.')
        for line in locked.lines.select_related('batch__product'):
            locked._post(locked.from_store, line.batch, line.qty, StockLedger.LedgerType.TRANSFER_IN)
        locked.status = self.Status.CANCELLED
        locked.discrepancy_note = f'Cancelled: {reason}'
        if locked.is_billed:
            locked.amount = Decimal('0')
        locked.save(update_fields=['status', 'discrepancy_note', 'amount'])
        self.refresh_from_db()

    @transaction.atomic
    def record_payment(self, *, payment_method, reference=''):
        """Hub mode: the main store records that the branch paid for a
        received transfer, in full."""
        locked = Transfer.objects.select_for_update().get(pk=self.pk)
        if not locked.is_billed:
            raise StockError('Only stock sent from the main store is paid for.')
        locked._require_status(self.Status.RECEIVED)
        if locked.paid_at:
            raise StockError('This transfer is already paid.')
        if not locked.amount:
            raise StockError('There is nothing to pay on this transfer.')
        reference = (reference or '').strip()
        if payment_method.requires_reference and not reference:
            raise StockError(f'Enter the {payment_method.name} transaction reference.')
        locked.payment_method = payment_method
        locked.payment_reference = reference
        locked.paid_at = timezone.now()
        locked.save(update_fields=['payment_method', 'payment_reference', 'paid_at'])
        self.refresh_from_db()


class TransferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name='lines')
    batch = models.ForeignKey(StockBatch, on_delete=models.PROTECT, related_name='+', help_text="The sender's batch.")
    qty = models.DecimalField(max_digits=12, decimal_places=2, help_text="Sent, in the product's own unit.")
    received_qty = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text='Cost per unit when sent.')

    def __str__(self):
        return f'{self.batch} x{self.qty}'
