"""What selling writes to the activity log (audit), apart from the
use cases themselves: the log needs the request (who, from where), which
the services deliberately never see. Summaries are English and translated
when the log is read."""

from audit.services import Action, Summary, record
from core.permissions import is_store_manager
from inventory.models import StockLedger


def discount(request, sale):
    """A discount over the cashier's limit is recorded with whoever
    allowed it — a manager at the till, or nobody (an offline sale)."""
    amount, gross, _limit, over_limit = sale.discount_check()
    if not over_limit:
        return
    by = sale.discount_approved_by
    if by:
        summary = Summary('Sale #{number}: discount TZS {discount:,.0f} of {gross:,.0f} (approved by {name})',
                          number=sale.number, discount=amount, gross=gross, name=by.username)
    else:
        who = 'given by a manager' if is_store_manager(sale.cashier, sale.store) else 'made offline, not approved'
        summary = Summary('Sale #{number}: discount TZS {discount:,.0f} of {gross:,.0f} ({who})',
                          number=sale.number, discount=amount, gross=gross, who=who)
    record(Action.DISCOUNT_GIVEN, summary,
           request=request, store=sale.store,
           data={'sale': str(sale.id), 'discount': amount, 'gross': gross,
                 'approved_by': by.username if by else ''})


def unrecorded_stock(request, sale):
    """An offline sale that sold more than the system had on record is
    kept (the goods were sold), and the owner is told which products, so
    a missing delivery or a wrong count can be found and entered."""
    entries = (StockLedger.objects.filter(ref_type='sale', ref_id=str(sale.id),
                                          ledger_type=StockLedger.LedgerType.UNRECORDED)
               .select_related('batch__product__uom'))
    items = [{'product': e.batch.product.name, 'qty': e.qty_delta, 'unit': e.batch.product.uom.name} for e in entries]
    if not items:
        return
    text = ', '.join(f'{i["product"]} {i["qty"].normalize():f} {i["unit"]}' for i in items)
    record(Action.OFFLINE_SALE_NO_STOCK,
           Summary('Sale #{number} was made offline for more stock than the system had: {items}. Check that every delivery was entered.',
                   number=sale.number, items=text),
           request=request, store=sale.store, data={'sale': str(sale.id), 'items': items})


def offline_prices(request, sale, price_changes):
    """An offline sale charged at prices that have changed since."""
    if not price_changes:
        return
    changes = '; '.join(f'{c["product"]} charged {c["charged"]:,.0f}, price now {c["current"]:,.0f}'
                        for c in price_changes)
    record(Action.OFFLINE_SALE_PRICE,
           Summary('Sale #{number} was made offline at old prices: {changes}', number=sale.number, changes=changes),
           request=request, store=sale.store, data={'sale': str(sale.id), 'changes': price_changes})


def voided(request, sale, approver, reason):
    record(Action.SALE_VOIDED,
           Summary('Sale #{number} ({total:,.0f}) voided: {reason}', number=sale.number, total=sale.total, reason=reason),
           request=request, store=sale.store,
           data={'sale': str(sale.id), 'approved_by': approver.username, 'efd_receipt_no': sale.efd_receipt_no})


def shift_closed(request, shift, z):
    record(Action.SHIFT_CLOSED,
           Summary('Shift of {username} closed: {sales_count} sales, difference {variance:,.0f}',
                   username=shift.cashier.username, sales_count=z['sales_count'], variance=z['variance']),
           request=request, store=shift.store,
           data={'shift': str(shift.id), 'expected_cash': z['expected_cash'], 'counted_cash': z['counted_cash'],
                 'variance': z['variance']})
