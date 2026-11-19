"""A physical stock take (see StockCount): draft (counting, blind) ->
submitted (expected quantities snapshotted) -> approved (differences
posted to the ledger), or cancelled."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext

from ..errors import StockError
from ..models import StockBatch, StockCount, StockCountLine, StockLedger
from ..stock import record_movement


def _require(count, *statuses):
    if count.status not in statuses:
        raise StockError(gettext('This count is {lower}.').format(lower=count.get_status_display().lower()))


@transaction.atomic
def start(*, store, user, products=None, note=''):
    """One line per batch the store holds; `products` limits it to a
    partial (cycle) count of just those products."""
    count = StockCount.objects.create(store=store, created_by=user, note=note)
    batches = StockBatch.objects.filter(store=store, qty_on_hand__gt=0).select_related('product')
    if products:
        batches = batches.filter(product__in=products)
    StockCountLine.objects.bulk_create([
        StockCountLine(count=count, batch=b, product=b.product, batch_no=b.batch_no, expiry_date=b.expiry_date)
        for b in batches.order_by('product__name', F('expiry_date').asc(nulls_last=True))
    ])
    return count


@transaction.atomic
def submit(count, *, user):
    """Ends counting: every line must be counted, and what the system
    expects is taken now, for the manager to compare."""
    _require(count, StockCount.Status.DRAFT)
    lines = list(count.lines.select_related('batch'))
    if not lines:
        raise StockError(gettext('There is nothing to count.'))
    uncounted = sum(1 for line in lines if line.counted_qty is None)
    if uncounted:
        raise StockError(gettext('{uncounted} line(s) are not counted yet. Enter 0 for anything not on the shelf.').format(uncounted=uncounted))
    for line in lines:
        line.expected_qty = line.batch.qty_on_hand if line.batch_id else 0
    StockCountLine.objects.bulk_update(lines, ['expected_qty'])
    count.status, count.submitted_by, count.submitted_at = StockCount.Status.SUBMITTED, user, timezone.now()
    count.save(update_fields=['status', 'submitted_by', 'submitted_at'])


@transaction.atomic
def approve(count, *, user):
    """Posts one 'stock_count' correction per batch whose count differs,
    creating the batch for stock found that the system had none of."""
    _require(count, StockCount.Status.SUBMITTED)
    for line in count.lines.select_related('batch__product', 'product'):
        delta = line.counted_qty - line.expected_qty
        if delta == 0:
            continue
        batch = line.batch
        if batch is None:
            batch = StockBatch.objects.create(
                store=count.store, product=line.product, batch_no=line.batch_no, expiry_date=line.expiry_date)
            line.batch = batch
        record_movement(
            store=count.store, batch=batch, qty_delta=delta,
            ledger_type=StockLedger.LedgerType.STOCK_COUNT, ref_type='stock_count', ref_id=count.id,
        )
        line.adjustment_qty = delta
        line.save(update_fields=['batch', 'adjustment_qty'])
    count.status, count.approved_by, count.approved_at = StockCount.Status.APPROVED, user, timezone.now()
    count.save(update_fields=['status', 'approved_by', 'approved_at'])


def reopen(count):
    """Back to counting, forgetting the expected quantities."""
    _require(count, StockCount.Status.SUBMITTED)
    count.lines.update(expected_qty=None)
    count.status = StockCount.Status.DRAFT
    count.save(update_fields=['status'])


def cancel(count):
    _require(count, StockCount.Status.DRAFT, StockCount.Status.SUBMITTED)
    count.status = StockCount.Status.CANCELLED
    count.save(update_fields=['status'])


def require_counting(count):
    """Refuses unless the count is still being counted (a draft)."""
    _require(count, StockCount.Status.DRAFT)


def check_none_in_progress(store):
    if StockCount.objects.filter(store=store, status__in=[StockCount.Status.DRAFT, StockCount.Status.SUBMITTED]).exists():
        raise StockError(gettext('This store already has a stock count in progress. Finish or cancel it first.'))


def record_counted(count, lines):
    """Saves the counted quantity already set on each of `lines` (lines
    of `count`)."""
    require_counting(count)
    StockCountLine.objects.bulk_update(lines, ['counted_qty'])


def add_found_stock(count, *, product, batch_no, expiry_date, counted_qty):
    """A line for stock on the shelf that the count sheet doesn't list:
    an existing batch the count left out, or one the system has no record
    of (created when the count is approved)."""
    require_counting(count)
    existing = StockBatch.objects.filter(
        store=count.store, product=product, batch_no=batch_no,
        **({'expiry_date': expiry_date} if not batch_no else {})).first()
    if existing and count.lines.filter(batch=existing).exists():
        label = (gettext('Batch {batch}').format(batch=batch_no) if batch_no
                 else gettext('{name} stock like this').format(name=product.name))
        raise StockError(gettext('{label} is already on this count sheet.').format(label=label))
    if existing is None and product.tracks_expiry and expiry_date is None:
        raise StockError(gettext('{name} expires: enter the expiry date on the pack.').format(name=product.name))
    return StockCountLine.objects.create(
        count=count, batch=existing, product=product, batch_no=batch_no,
        expiry_date=existing.expiry_date if existing else expiry_date, counted_qty=counted_qty,
    )
