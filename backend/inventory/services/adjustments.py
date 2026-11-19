from django.db import transaction
from django.utils.translation import gettext

from ..errors import StockError
from ..models import StockAdjustment
from ..stock import record_movement


@transaction.atomic
def apply(*, batch, qty_delta, reason, note, user):
    """Takes stock off `batch` (or, only to correct a wrong entry, puts it
    back) for `reason`, which doubles as the ledger type, so every loss
    shows in reports. Returns the StockAdjustment."""
    if qty_delta == 0:
        raise StockError(gettext('Quantity must not be zero.'))
    if qty_delta > 0 and reason != StockAdjustment.Reason.WRONG_ENTRY:
        raise StockError(gettext('Only "Correcting a wrong entry" can add stock; use Receiving for new stock.'))
    entry = record_movement(
        store=batch.store, batch=batch, qty_delta=qty_delta, ledger_type=reason, ref_type='stock_adjustment',
    )
    adjustment = StockAdjustment.objects.create(
        store=batch.store, batch=batch, qty_delta=qty_delta, reason=reason, note=note,
        created_by=user, ledger_entry=entry,
    )
    entry.ref_id = str(adjustment.id)
    entry.save(update_fields=['ref_id'])
    return adjustment
