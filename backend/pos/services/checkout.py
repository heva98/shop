"""Turning a cart into a sale: completing it (payment, stock, receipt
number), recording one the till already made offline, and voiding one."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext

from catalog.models import sell_unit
from core import features
from core.models import Store
from core.money import ZERO, money, split
from core.permissions import is_store_manager
from inventory.models import StockBatch, StockLedger
from inventory.stock import record_movement

from ..domain import Prescription, check_sale_discount, check_tender
from ..errors import SaleError
from ..events import sale_line_stock_moved
from ..models import Sale, Shift
from . import cart, fiscal


@transaction.atomic
def complete(sale, *, user, payment_method, amount_tendered=None, payment_reference='',
             customer=None, credit_amount=Decimal('0'), customer_name='', discount=Decimal('0'),
             discount_approver=None, shift=None, completed_at=None, enforce_limits=True,
             patient_name='', prescriber_name='', prescription_ref=''):
    """Takes payment, deducts stock, numbers and locks the sale, then
    asks the store's fiscal driver for a receipt. Returns the
    FiscalResult so the till can show printed / failed / 'enter EFD
    receipt number'.

    `discount` comes off the whole sale (on top of any line discounts);
    beyond the entity's cashier_discount_limit it needs a manager, as
    the user or as `discount_approver`. `credit_amount` of the total
    goes on `customer`'s account, and the payment method covers the
    rest. `enforce_limits=False` records an offline sale that already
    happened even if it broke those limits.

    Pharmacies: for medicine that needs a prescription the till asks
    for `patient_name`, `prescriber_name` and `prescription_ref`; they
    are optional (the shop's choice), kept on the sale and passed on
    (pos.events) to the controlled drugs register with whoever sold it.
    Anyone who can sell may sell a controlled drug, cashiers included
    (the shop's choice); the store must have the register switched on.

    `shift` and `completed_at` are for a sale the till recorded
    offline: the cashier's shift it was rung up in (even if closed
    since) and when it happened. Default: the open shift, now."""
    # The lines are read once here: the checks, totals and stock
    # deduction below all work from this copy (lines.all()).
    locked = (Sale.objects.select_for_update().select_related('store__entity')
              .prefetch_related('lines__batch__product').get(pk=sale.pk))
    locked.require_status(Sale.Status.OPEN, 'complete')
    if not locked.lines.exists():
        raise SaleError(gettext('The cart is empty.'))
    shift = _selling_shift(locked, user, shift, allow_closed=not enforce_limits)
    now = timezone.now()
    completed_at = now if completed_at is None or completed_at > now else completed_at
    rx = _prescription(locked, patient_name, prescriber_name, prescription_ref)

    # The checks run in this order so the cashier sees the same first
    # problem whichever way the sale arrives.
    if not payment_method.is_active_for(locked.store.entity_id):
        raise SaleError(gettext('{name} is not enabled.').format(name=payment_method.name))
    if discount:
        _apply_sale_discount(locked, discount)
    approved_by = _check_discount_limit(locked, user, discount_approver) if enforce_limits else None
    total = locked.total
    credit_amount = money(credit_amount or 0)
    _check_credit(locked, customer, credit_amount, total, enforce_limits)
    amount_tendered, payment_reference = check_tender(
        payment_method, total - credit_amount, amount_tendered, payment_reference)

    _deduct_stock(locked, user, rx, allow_shortfall=not enforce_limits)
    locked.status = Sale.Status.COMPLETED
    locked.number = _next_number(locked)
    locked.cashier = user
    locked.shift = shift
    locked.payment_method = payment_method
    locked.amount_tendered = amount_tendered
    locked.payment_reference = payment_reference
    locked.customer = customer
    locked.credit_amount = credit_amount
    locked.customer_name = (customer.name if customer is not None else (customer_name or '').strip())[:255]
    locked.discount_approved_by = approved_by
    locked.patient_name, locked.prescriber_name, locked.prescription_ref = (
        rx.patient_name, rx.prescriber_name, rx.prescription_ref)
    locked.completed_at = completed_at
    locked.save()
    sale.refresh_from_db()
    return fiscal.fiscalize(sale)


@transaction.atomic
def record_offline(*, id, store, user, items, strict=False, shift=None, completed_at=None,
                   efd_receipt_no='', **payment):
    """Records, in one go, a whole sale the till rang up from its own
    copy of the catalog — while offline, or just now (strict). Returns
    (sale, fiscal_result, price_changes).

    Prices: the till sends what it charged. When the store's price has
    changed since the till's copy, a strict (just-now) sale is refused
    so the cashier can re-check the total with the customer still
    there; an offline sale already happened, so it is recorded at the
    price actually charged and the difference returned for auditing.
    The same goes for the cashier's discount limit and a customer's
    credit limit: enforced on a strict sale, recorded (and audited by
    the caller) on an offline one.

    Stock and every other rule are checked exactly as for a sale made
    online; a refusal leaves nothing behind, so the till can retry."""
    sale = Sale.objects.create(id=id, store=store, cashier=user)
    price_changes = []
    for item in items:
        product, uom, charged = item['product'], item.get('uom'), item['unit_price']
        price = cart.current_price(store, product, sell_unit(product, uom))
        if price is not None and price != charged:
            if strict:
                raise SaleError(
                    gettext('The price of {name} has changed to TZS {price:,.0f}. The cart now shows the new price: check the total with the customer.').format(name=product.name, price=price))
            price_changes.append({'product': product.name, 'charged': charged, 'current': price})
        # strict: the price just checked (None lets add_product refuse it
        # with its own message); offline: what the customer paid.
        cart.add_product(sale, product=product, qty=item['qty'], uom=uom, unit_price=price if strict else charged,
                         discount=item.get('discount') or ZERO, allow_shortfall=not strict)
    result = complete(sale, user=user, shift=shift, completed_at=completed_at, enforce_limits=strict, **payment)
    if efd_receipt_no:
        # A duplicate or mistyped number must not lose the sale: it can
        # be entered again from the shift's sales list.
        try:
            with transaction.atomic():
                fiscal.record_receipt(sale, receipt_number=efd_receipt_no, user=user)
        except SaleError:
            pass
    return sale, result, price_changes


@transaction.atomic
def void(sale, *, user, approver, reason):
    """Reverses a completed sale: every line's quantity goes back to the
    batch it came from (a 'sale_void' ledger entry, so the ledger still
    shows both movements). A credit sale's amount stops counting
    against the customer's balance, since that is computed from
    completed sales only. `approver` must already have been checked
    as a manager for this store by the caller."""
    locked = Sale.objects.select_for_update().get(pk=sale.pk)
    locked.require_status(Sale.Status.COMPLETED, 'void')
    reason = (reason or '').strip()
    if not reason:
        raise SaleError(gettext('Give a reason for voiding this sale.'))
    rx = Prescription.of_sale(locked)
    for line in locked.lines.select_related('batch__product'):
        entry = record_movement(
            store=locked.store, batch=line.batch, qty_delta=line.qty,
            ledger_type=StockLedger.LedgerType.SALE_VOID, ref_type='sale', ref_id=locked.id,
        )
        sale_line_stock_moved.send(Sale, sale=locked, line=line, ledger_entry=entry, user=user,
                                   prescription=rx, returned=True)
    locked.status = Sale.Status.VOIDED
    locked.voided_at = timezone.now()
    locked.voided_by = user
    locked.void_approved_by = approver
    locked.void_reason = reason
    locked.save(update_fields=['status', 'voided_at', 'voided_by', 'void_approved_by', 'void_reason'])
    sale.refresh_from_db()


# --- Steps of complete() --------------------------------------------------

def _selling_shift(sale, user, shift, *, allow_closed):
    """`shift` when it is the user's own at this store, else the user's
    open shift here. Refuses when there is neither.

    A closed `shift` is only taken when `allow_closed`: an offline sale
    was rung up in it before it closed and still belongs to it. A sale
    being made now must not go into a closed shift, whose drawer has
    already been counted; it goes to the open one or is refused.

    The shift row is locked, so a sale and the shift's close cannot
    interleave: the sale is in the count, or it sees the shift closed."""
    named = None
    if shift is not None and shift.store_id == sale.store_id and shift.cashier_id == user.pk:
        named = Shift.objects.select_for_update().filter(pk=shift.pk).first()
        if named is not None and not named.is_open and not allow_closed:
            named = None
    shift = named or Shift.open_for(store=sale.store, cashier=user).select_for_update().first()
    if shift is None:
        raise SaleError(gettext('Open a shift before selling.'))
    return shift


def _prescription(sale, patient_name, prescriber_name, prescription_ref):
    """The prescription details for medicine that needs one (all
    optional); empty for any other sale."""
    if not any(line.batch.product.needs_prescription for line in sale.lines.all()):
        return Prescription()
    return Prescription.from_input(patient_name, prescriber_name, prescription_ref)


def _apply_sale_discount(sale, discount):
    """A discount off the whole sale, shared over the lines in
    proportion to their amounts so every line (and the VAT on it)
    reflects what was really charged."""
    lines = list(sale.lines.all())
    discount = check_sale_discount(discount, sum((line.amount for line in lines), ZERO))
    for line, share in zip(lines, split(discount, [line.amount for line in lines])):
        line.discount += share
        line.amount -= share
        line.save(update_fields=['discount', 'amount'])


def _check_discount_limit(sale, user, approver):
    """Returns the manager who approved the discount, if one was needed.
    Raises if the discount is over the cashier's limit and nobody with
    the authority gave it."""
    discount, _gross, limit, over_limit = sale.discount_check()
    if not over_limit or is_store_manager(user, sale.store):
        return None
    if approver is not None and is_store_manager(approver, sale.store):
        return approver
    raise SaleError(gettext('A discount of TZS {discount:,.0f} is more than the {normalize:f}% a cashier may give. A manager must approve it.').format(discount=discount, normalize=limit.normalize()))


def _check_credit(sale, customer, credit_amount, total, enforce_limit):
    store = sale.store
    if customer is not None and (customer.entity_id != store.entity_id or not customer.is_active):
        raise SaleError(gettext("Choose one of the shop's active customers."))
    if not credit_amount:
        return
    if not features.is_enabled('customer_credit', store=store):
        raise SaleError(gettext('{name} does not sell on credit. An admin can switch it on under Settings > Features.').format(name=store.name))
    if customer is None:
        raise SaleError(gettext('Choose the customer this sale is on credit to.'))
    if credit_amount < 0 or credit_amount > total:
        raise SaleError(gettext('The amount on credit must be between 0 and the total of TZS {total:,.0f}.').format(total=total))
    if enforce_limit and customer.credit_limit is not None:
        owing = customer.balance()
        if owing + credit_amount > customer.credit_limit:
            raise SaleError(
                gettext('{name} already owes TZS {owing:,.0f}; their credit limit is TZS {credit_limit:,.0f}. Take at most TZS {max:,.0f} on credit.').format(name=customer.name, owing=owing, credit_limit=customer.credit_limit, max=max(customer.credit_limit - owing, 0)))


def _deduct_stock(sale, user, rx, *, allow_shortfall):
    """Takes every line off its batch, telling pos.events listeners (the
    controlled drugs register) about each one.

    `allow_shortfall` (an offline sale, which already happened): when
    a batch holds less than the line sold, the missing units are first
    put on it as 'sold without recorded stock', so the sale is never
    lost and stock never goes negative. Without it, too little stock
    refuses the whole sale (InsufficientStockError).

    Called by complete(), which has the lines and their products
    prefetched."""
    for line in sale.lines.all():
        if allow_shortfall:
            on_hand = StockBatch.objects.select_for_update().get(pk=line.batch_id).qty_on_hand
            if on_hand < line.qty:
                record_movement(
                    store=sale.store, batch=line.batch, qty_delta=line.qty - on_hand,
                    ledger_type=StockLedger.LedgerType.UNRECORDED, ref_type='sale', ref_id=sale.id,
                )
        entry = record_movement(
            store=sale.store, batch=line.batch, qty_delta=-line.qty,
            ledger_type=StockLedger.LedgerType.SOLD, ref_type='sale', ref_id=sale.id,
        )
        sale_line_stock_moved.send(Sale, sale=sale, line=line, ledger_entry=entry, user=user,
                                   prescription=rx, returned=False)


def _next_number(sale):
    """The store's next receipt number. The store row lock serializes
    numbering, so two tills can never be handed the same number."""
    Store.objects.select_for_update().get(pk=sale.store_id)
    # number__isnull lets Postgres answer from the unique (store, number)
    # index, which only covers numbered sales.
    last = Sale.objects.filter(store_id=sale.store_id, number__isnull=False).aggregate(n=Max('number'))['n']
    return (last or 0) + 1
