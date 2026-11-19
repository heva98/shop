"""The kernel's stock API: how every module moves and picks stock.

    record_movement()  the only sanctioned way to change a batch's quantity
    allocate_fefo()    which batches a quantity comes from, earliest expiry first
    sellable_batches() / fefo_batches() / shortfall_batch()

Selling, receiving, transfers, counts and adjustments all go through
here, so the ledger and qty_on_hand can never drift apart, whichever
module moved the stock."""

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext

from .errors import InsufficientStockError
from .models import StockBatch, StockLedger


@transaction.atomic
def record_movement(*, store, batch, qty_delta, ledger_type, ref_type='', ref_id=''):
    """Locks the batch, writes the ledger row, and applies qty_delta to the
    batch in one transaction, so the ledger and qty_on_hand can never drift
    apart and two concurrent calls against the same batch can't both
    succeed past zero. A positive delta (receiving, transfer in) is never
    blocked — only a delta that would take the batch negative is. Returns
    the StockLedger entry; `batch.qty_on_hand` is updated too."""
    locked = StockBatch.objects.select_for_update().get(pk=batch.pk)
    new_qty = locked.qty_on_hand + qty_delta
    if new_qty < 0:
        raise InsufficientStockError(
            gettext('{locked} has {qty_on_hand} on hand; cannot apply {qty_delta}.').format(locked=locked, qty_on_hand=locked.qty_on_hand, qty_delta=qty_delta),
        )
    entry = StockLedger.objects.create(
        store=store, batch=locked, qty_delta=qty_delta, ledger_type=ledger_type,
        ref_type=ref_type, ref_id=str(ref_id),
    )
    locked.qty_on_hand = new_qty
    locked.save(update_fields=['qty_on_hand'])
    batch.qty_on_hand = new_qty
    return entry


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
def allocate_fefo(store, product, qty, *, reserved=None, allow_shortfall=False):
    """Picks which batch(es) to deduct `qty` of `product` from at `store`,
    earliest-expiring first, splitting across batches when one isn't
    enough. Returns a list of (batch, qty_from_that_batch) pairs covering
    the full requested quantity. Locks every batch it considers so two
    concurrent allocations can't both plan against the same stock.

    `reserved` is {batch id: qty} already planned but not yet deducted
    (earlier lines of the same cart), so two lines for one product don't
    both plan on the same units.

    Raises InsufficientStockError if the store doesn't have enough total
    unexpired stock of the product to cover qty, without touching anything
    — unless `allow_shortfall`: a sale that already happened offline, so
    the goods were on the shelf even if the system has no record of them.
    The rest is then planned on shortfall_batch(), and the sale records
    those units as 'sold without recorded stock' when it is completed.
    """
    reserved = reserved or {}
    remaining = qty
    plan = []
    batches = fefo_batches(store, product).select_for_update()
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.qty_on_hand - reserved.get(batch.pk, 0), remaining)
        if take <= 0:
            continue
        plan.append((batch, take))
        remaining -= take
    if remaining > 0:
        if not allow_shortfall:
            raise InsufficientStockError(
                gettext('Not enough unexpired stock of {product} at {store}: short by {remaining}.').format(product=product, store=store, remaining=remaining),
            )
        fallback = plan[-1][0] if plan else shortfall_batch(store, product)
        if plan:
            plan[-1] = (fallback, plan[-1][1] + remaining)
        else:
            plan.append((fallback, remaining))
    return plan


def shortfall_batch(store, product):
    """The batch to put units on that were sold but never recorded as
    received: the store's latest delivery of the product (most likely
    what was on the shelf), or else a new empty batch costed like the
    shop's latest delivery of it anywhere, so profit reports stay sensible."""
    batch = StockBatch.objects.filter(store=store, product=product).order_by('-created_at').first()
    if batch is not None:
        return batch
    latest = StockBatch.objects.filter(product=product).order_by('-created_at').first()
    return StockBatch.objects.create(store=store, product=product, unit_cost=latest.unit_cost if latest else 0)
