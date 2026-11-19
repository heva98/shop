"""Receiving use cases: posting a supplier's invoice to stock, and paying
the supplier for it."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from catalog.models import convert_qty
from inventory.errors import StockError
from inventory.models import StockBatch, StockLedger
from inventory.stock import record_movement

from .models import ReceivingInvoice, SupplierPayment


@transaction.atomic
def receive(invoice):
    """Locks the invoice and posts every line to stock: creates or tops
    up the named batch and writes a Transfer In ledger entry per line,
    referencing this invoice. Receiving an invoice twice does nothing."""
    if invoice.status == ReceivingInvoice.Status.RECEIVED:
        return
    lines = list(invoice.lines.select_related('product__uom', 'uom'))
    if not lines:
        raise StockError(gettext('Add at least one line before receiving the invoice.'))
    missing = [line.product.name for line in lines if line.product.tracks_expiry and not line.expiry_date]
    if missing:
        raise StockError(gettext('These goods expire, so the expiry date is required for: {join}.').format(join=", ".join(missing)))
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
            store=invoice.store, product=line.product, **batch_key,
            defaults={'expiry_date': line.expiry_date, 'unit_cost': unit_cost},
        )
        if not created and batch.unit_cost == 0:
            batch.unit_cost = unit_cost
            batch.save(update_fields=['unit_cost'])
        record_movement(
            store=invoice.store, batch=batch, qty_delta=qty,
            ledger_type=StockLedger.LedgerType.TRANSFER_IN,
            ref_type='receiving_invoice', ref_id=invoice.id,
        )
    invoice.status = ReceivingInvoice.Status.RECEIVED
    invoice.received_at = timezone.now()
    if invoice.due_date is None:
        invoice.refresh_from_db(fields=['received_date'])  # may still be the string it was created with
        invoice.due_date = invoice.received_date + timedelta(days=invoice.supplier.payment_terms_days)
    invoice.save(update_fields=['status', 'received_at', 'due_date'])


@transaction.atomic
def record_payment(invoice, *, amount, paid_on, method, reference, user):
    """Money paid to the supplier against a received invoice, never more
    than is still owed on it."""
    locked = ReceivingInvoice.objects.select_for_update().get(pk=invoice.pk)
    if locked.status != ReceivingInvoice.Status.RECEIVED:
        raise StockError(gettext('Receive the invoice before recording a payment against it.'))
    if amount <= 0:
        raise StockError(gettext('Payment amount must be above zero.'))
    if amount > locked.balance:
        raise StockError(gettext('That is more than the {balance:,.0f} still owed on this invoice.').format(balance=locked.balance))
    return SupplierPayment.objects.create(
        invoice=locked, amount=amount, paid_on=paid_on, method=method, reference=reference, recorded_by=user,
    )
