"""Moving stock between two stores of a firm (see Transfer for the
lifecycle). Every movement is a ledger entry referencing the transfer."""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext

from core import features
from core.models import Entity
from inventory.errors import StockError
from inventory.models import StockBatch, StockLedger
from inventory.stock import allocate_fefo, record_movement

from ..models import Transfer, TransferLine

Status = Transfer.Status
Resolution = Transfer.Resolution


def _require_status(transfer, *statuses):
    if transfer.status not in statuses:
        raise StockError(gettext('This transfer is {lower}.').format(lower=transfer.get_status_display().lower()))


def _post(transfer, store, batch, qty, ledger_type):
    return record_movement(store=store, batch=batch, qty_delta=qty, ledger_type=ledger_type,
                           ref_type='transfer', ref_id=transfer.id)


def _receiving_batch(transfer, line):
    """The receiving store's batch matching the one sent: same batch
    number, or for goods without one, the same expiry date."""
    sent = line.batch
    key = {'batch_no': sent.batch_no} if sent.batch_no else {'batch_no': '', 'expiry_date': sent.expiry_date}
    batch, _ = StockBatch.objects.get_or_create(
        store=transfer.to_store, product=sent.product, **key,
        defaults={'expiry_date': sent.expiry_date, 'unit_cost': line.unit_cost or sent.unit_cost},
    )
    return batch


def _rebill(transfer):
    """A hub branch pays for what it actually got."""
    if transfer.is_billed:
        transfer.amount = sum(
            ((line.qty if line.received_qty is None else line.received_qty) * line.unit_cost
             for line in transfer.lines.all()),
            Decimal('0'),
        ).quantize(Decimal('0.01'))


def _plan(item, from_store, entity):
    """[(batch, qty)] for one item to send: that batch exactly, or the
    product's batches earliest-expiry first."""
    try:
        qty = Decimal(str(item['qty']))
    except (InvalidOperation, KeyError):
        raise StockError(gettext('Every line needs a quantity.'))
    if qty <= 0:
        raise StockError(gettext('Quantities must be more than zero.'))
    batch = item.get('batch')
    if batch is not None:
        if batch.store_id != from_store.id:
            raise StockError(gettext('Batch {batch_no} is not at {name}.').format(batch_no=batch.batch_no, name=from_store.name))
        if batch.is_expired:
            raise StockError(gettext('Batch {batch_no} has expired and cannot be sent.').format(batch_no=batch.batch_no))
        return [(StockBatch.objects.select_for_update().get(pk=batch.pk), qty)]
    product = item['product']
    if product.entity_id != entity.id:
        raise StockError(gettext("Product is not in this shop's catalog."))
    return allocate_fefo(from_store, product, qty)


@transaction.atomic
def send(*, from_store, to_store, items, user=None, enquiry=None, note=''):
    """Creates and dispatches a transfer. `items` is a list of
    {'product': Product, 'qty': n} (batches picked earliest-expiry
    first, so expired stock is never sent) or {'batch': StockBatch,
    'qty': n} (that batch exactly). Quantities are in the product's own
    unit."""
    if from_store.id == to_store.id:
        raise StockError(gettext('Choose a different store to send to.'))
    if from_store.entity_id != to_store.entity_id:
        raise StockError(gettext('Stock can only move between stores of the same shop.'))
    if not to_store.is_active:
        raise StockError(gettext('{name} is deactivated.').format(name=to_store.name))
    features.require('transfer', entity=from_store.entity_id)
    if not items:
        raise StockError(gettext('Add at least one product to send.'))

    # The entity row lock serializes numbering across the firm.
    entity = Entity.objects.select_for_update().get(pk=from_store.entity_id)
    last = Transfer.objects.filter(from_store__entity=entity).aggregate(n=Max('number'))['n'] or 0
    transfer = Transfer.objects.create(
        number=last + 1, enquiry=enquiry, from_store=from_store, to_store=to_store,
        mode=Transfer.Mode.HUB if entity.main_store_id == from_store.id else Transfer.Mode.PEER,
        note=(note or '').strip()[:255], dispatched_by=user,
    )
    for item in items:
        for batch, qty in _plan(item, from_store, entity):
            TransferLine.objects.create(transfer=transfer, batch=batch, qty=qty, unit_cost=batch.unit_cost)
            _post(transfer, from_store, batch, -qty, StockLedger.LedgerType.TRANSFER_OUT)
    if transfer.is_billed:
        _rebill(transfer)
        transfer.save(update_fields=['amount'])
    return transfer


@transaction.atomic
def confirm_receipt(transfer, *, user=None, received_qty_by_line: dict = None, note=''):
    """The receiving store counts what arrived. Lines missing from
    received_qty_by_line (line id -> qty) arrived in full. Less than
    was sent on any line flags a short delivery (a note is required)
    until a manager resolves it; more than was sent is refused."""
    locked = Transfer.objects.select_for_update().get(pk=transfer.pk)
    _require_status(locked, Status.DISPATCHED)
    received = {str(k): v for k, v in (received_qty_by_line or {}).items()}
    note = (note or '').strip()
    counted = []
    for line in locked.lines.select_related('batch__product'):
        try:
            qty = Decimal(str(received.get(str(line.id), line.qty)))
        except InvalidOperation:
            raise StockError(gettext('Received quantities must be numbers.'))
        if qty < 0:
            raise StockError(gettext('Received quantities cannot be negative.'))
        if qty > line.qty:
            raise StockError(gettext('{name}: {qty} received but only {qty2} were sent. Count again.').format(name=line.batch.product.name, qty=qty, qty2=line.qty))
        counted.append((line, qty))
    short = any(qty < line.qty for line, qty in counted)
    if short and not note:
        raise StockError(gettext('Less arrived than was sent: add a note saying what is missing.'))

    for line, qty in counted:
        if qty > 0:
            _post(locked, locked.to_store, _receiving_batch(locked, line), qty, StockLedger.LedgerType.TRANSFER_IN)
        line.received_qty = qty
        line.save(update_fields=['received_qty'])
    locked.status = Status.DISCREPANCY if short else Status.RECEIVED
    locked.discrepancy_note = note if short else ''
    locked.received_by = user
    locked.received_at = timezone.now()
    _rebill(locked)
    locked.save(update_fields=['status', 'discrepancy_note', 'received_by', 'received_at', 'amount'])
    transfer.refresh_from_db()


@transaction.atomic
def resolve(transfer, *, resolution, user=None, note=''):
    """Settles a short delivery. return_to_sender: the missing units
    never left (or came back), so they go back into the sender's batch.
    received_late: they turned up at the receiver, so they're added
    there (and billed). write_off: lost on the way, booked as a loss at
    the sending store so it shows in the losses report."""
    locked = Transfer.objects.select_for_update().get(pk=transfer.pk)
    _require_status(locked, Status.DISCREPANCY)
    if resolution not in Resolution.values:
        raise StockError(gettext('Choose what happened to the missing stock.'))
    for line in locked.lines.select_related('batch__product'):
        missing = line.qty - (line.received_qty or 0)
        if missing <= 0:
            continue
        if resolution == Resolution.RECEIVED_LATE:
            _post(locked, locked.to_store, _receiving_batch(locked, line), missing, StockLedger.LedgerType.TRANSFER_IN)
            line.received_qty = line.qty
            line.save(update_fields=['received_qty'])
            continue
        _post(locked, locked.from_store, line.batch, missing, StockLedger.LedgerType.TRANSFER_IN)
        if resolution == Resolution.WRITE_OFF:
            _post(locked, locked.from_store, line.batch, -missing, StockLedger.LedgerType.LOST)
    note = (note or '').strip()
    locked.status = Status.RECEIVED
    locked.resolution = resolution
    locked.discrepancy_note = '\n'.join(filter(None, [
        locked.discrepancy_note, f'Resolved: {Resolution(resolution).label}' + (f' — {note}' if note else ''),
    ]))
    _rebill(locked)
    locked.save(update_fields=['status', 'resolution', 'discrepancy_note', 'amount'])
    transfer.refresh_from_db()


@transaction.atomic
def cancel(transfer, *, user=None, reason=''):
    """The sender calls a transfer back before it is received: every
    line goes back into the batch it came from."""
    locked = Transfer.objects.select_for_update().get(pk=transfer.pk)
    _require_status(locked, Status.DISPATCHED)
    reason = (reason or '').strip()
    if not reason:
        raise StockError(gettext('Give a reason for cancelling this transfer.'))
    for line in locked.lines.select_related('batch__product'):
        _post(locked, locked.from_store, line.batch, line.qty, StockLedger.LedgerType.TRANSFER_IN)
    locked.status = Status.CANCELLED
    locked.discrepancy_note = f'Cancelled: {reason}'
    if locked.is_billed:
        locked.amount = Decimal('0')
    locked.save(update_fields=['status', 'discrepancy_note', 'amount'])
    transfer.refresh_from_db()


@transaction.atomic
def record_payment(transfer, *, payment_method, reference=''):
    """Hub mode: the main store records that the branch paid for a
    received transfer, in full."""
    locked = Transfer.objects.select_for_update().get(pk=transfer.pk)
    if not locked.is_billed:
        raise StockError(gettext('Only stock sent from the main store is paid for.'))
    _require_status(locked, Status.RECEIVED)
    if locked.paid_at:
        raise StockError(gettext('This transfer is already paid.'))
    if not locked.amount:
        raise StockError(gettext('There is nothing to pay on this transfer.'))
    reference = (reference or '').strip()
    if payment_method.requires_reference and not reference:
        raise StockError(gettext('Enter the {name} transaction reference.').format(name=payment_method.name))
    locked.payment_method = payment_method
    locked.payment_reference = reference
    locked.paid_at = timezone.now()
    locked.save(update_fields=['payment_method', 'payment_reference', 'paid_at'])
    transfer.refresh_from_db()
