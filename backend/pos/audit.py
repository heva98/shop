"""What selling writes to the activity log (audit), apart from the
use cases themselves: the log needs the request (who, from where), which
the services deliberately never see. Summaries are English and translated
when the log is read."""

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

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
    unapproved = False
    if by:
        summary = Summary('Sale #{number}: discount TZS {discount:,.0f} of {gross:,.0f} (approved by {name})',
                          number=sale.number, discount=amount, gross=gross, name=by.username)
    else:
        unapproved = not is_store_manager(sale.cashier, sale.store)
        who = 'made offline, not approved' if unapproved else 'given by a manager'
        summary = Summary('Sale #{number}: discount TZS {discount:,.0f} of {gross:,.0f} ({who})',
                          number=sale.number, discount=amount, gross=gross, who=who)
    # `unapproved` is what audit.alerts reports to the owner.
    record(Action.DISCOUNT_GIVEN, summary,
           request=request, store=sale.store,
           data={'sale': str(sale.id), 'discount': amount, 'gross': gross,
                 'approved_by': by.username if by else '', 'unapproved': unapproved})


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


def _local(moment):
    return f'{timezone.localtime(moment):%d/%m/%Y %H:%M}'


def offline_limits(request, sale, dated):
    """An offline sale is kept whatever it broke (the goods are gone),
    but the server checks what it can and logs each problem as
    OFFLINE_SALE_LIMIT, which audit.alerts texts to the owner: credit
    over the customer's limit, and a date (`dated`, as the till sent it)
    outside the shift the sale was recorded in or long before it arrived.
    A discount over the cashier's limit is logged by discount() above;
    a price that differs from the store's, by offline_prices()."""
    base = {'sale': str(sale.id), 'number': sale.number}
    customer = sale.customer
    if customer is not None and sale.credit_amount and customer.credit_limit is not None:
        owing = customer.balance()
        if owing > customer.credit_limit:
            record(Action.OFFLINE_SALE_LIMIT,
                   Summary('Sale #{number} was made offline on credit to {customer}, who now owes TZS {owing:,.0f} '
                           '(limit {limit:,.0f})', number=sale.number, customer=customer.name, owing=owing,
                           limit=customer.credit_limit),
                   request=request, store=sale.store,
                   data={**base, 'reason': 'credit_limit', 'owing': owing, 'limit': customer.credit_limit})
    if dated is None:
        return
    grace = timedelta(minutes=settings.OFFLINE_SALE_CLOCK_GRACE_MINUTES)
    shift = sale.shift
    if shift is not None and (dated < shift.opened_at - grace or (shift.closed_at and dated > shift.closed_at + grace)):
        record(Action.OFFLINE_SALE_LIMIT,
               Summary('Sale #{number} is dated {when}, outside the shift it was recorded in ({opened} to {closed})',
                       number=sale.number, when=_local(dated), opened=_local(shift.opened_at),
                       closed=_local(shift.closed_at) if shift.closed_at else 'now'),
               request=request, store=sale.store, data={**base, 'reason': 'outside_shift', 'dated': dated.isoformat()})
    age = timezone.now() - dated
    if age > timedelta(hours=settings.OFFLINE_SALE_MAX_AGE_HOURS):
        record(Action.OFFLINE_SALE_LIMIT,
               Summary('Sale #{number} is dated {when}, {hours} hours before it reached the server',
                       number=sale.number, when=_local(dated), hours=int(age.total_seconds() // 3600)),
               request=request, store=sale.store, data={**base, 'reason': 'too_old', 'dated': dated.isoformat()})


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
