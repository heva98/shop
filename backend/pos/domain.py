"""Selling rules that need no database.

How a sale was paid, what a drawer should hold, how one cart item is
shared over the batches it comes from, whether a tender covers what is
due: pure functions over plain values and already-loaded objects. They
never query or save, so they can be tested alone, and reports reuse them
to get the same answers as the till without loading whole sales.

The services in pos.services decide *when* these rules apply and do the
reading and writing around them."""

from dataclasses import dataclass
from decimal import Decimal

from django.utils.translation import gettext

from core.money import ZERO, money, split
from payments.models import PaymentMethod

from .errors import SaleError

CASH = PaymentMethod.Implementation.CASH


# --- Payments -------------------------------------------------------------

def split_payment(method_name, implementation, total, credit_amount):
    """[(name, implementation, amount)]: how a sale of `total` was paid. The
    part paid now goes to the payment method and `credit_amount` to the
    customer's account. Sale.payment_split for one sale; reports call it
    with plain values so they needn't load whole sales."""
    parts = []
    if total - credit_amount > 0 or not credit_amount:
        parts.append((method_name, implementation, total - credit_amount))
    if credit_amount:
        parts.append((gettext('On credit'), 'credit', credit_amount))
    return parts


def payment_rows(entries):
    """{method name: {payment_method, implementation, count, total}} from
    (name, implementation, amount) triples."""
    rows = {}
    for name, implementation, amount in entries:
        row = rows.setdefault(name, {'payment_method': name, 'implementation': implementation, 'count': 0, 'total': ZERO})
        row['count'] += 1
        row['total'] += amount
    return rows


def cash_total(rows):
    """The cash share of payment_rows(): what went into the drawer."""
    return sum((r['total'] for r in rows.values() if r['implementation'] == CASH), ZERO)


def check_tender(payment_method, payable, amount_tendered, payment_reference):
    """(amount_tendered, payment_reference) to record. Cash must cover
    what is payable and carries no reference; any other method needs a
    transaction reference and is taken for exactly the amount due."""
    if payment_method.implementation == CASH:
        if payable == 0 and amount_tendered is None:
            amount_tendered = Decimal('0')
        if amount_tendered is None or amount_tendered < payable:
            raise SaleError(gettext('Amount tendered must cover the total of TZS {payable:,.0f}.').format(payable=payable))
        return amount_tendered, ''
    payment_reference = (payment_reference or '').strip()
    if payable > 0 and not payment_reference:
        raise SaleError(gettext('Enter the {name} transaction reference.').format(name=payment_method.name))
    return payable, payment_reference


# --- Discounts ------------------------------------------------------------

def discount_over_limit(discount, gross, limit_percent):
    """Whether `discount` off `gross` is more than a cashier may give
    (`limit_percent`, the entity's cashier_discount_limit)."""
    return bool(discount) and discount * 100 > gross * limit_percent


def check_item_discount(product_name, gross, discount):
    """The discount on one cart item, rounded; refused unless it is
    between 0 and the item's gross amount."""
    discount = money(discount or 0)
    if discount < 0 or discount > gross:
        raise SaleError(gettext('The discount on {name} must be between 0 and TZS {gross:,.0f}.').format(name=product_name, gross=gross))
    return discount


def check_sale_discount(discount, total):
    """A discount off the whole sale, rounded; refused unless it is
    between 0 and the sale's total."""
    discount = money(discount)
    if discount < 0 or discount > total:
        raise SaleError(gettext('The discount must be between 0 and TZS {total:,.0f}.').format(total=total))
    return discount


# --- Cart items over batches ----------------------------------------------

def share_over_batches(qty, base_qty, gross, discount, batch_quantities):
    """[(sell_qty, gross, discount)], one per batch, for a cart item of
    `qty` (in the unit sold, `base_qty` in the product's own unit) taken
    from batches holding `batch_quantities` of it. Each batch gets its share
    of the quantity, amount and discount, and the last takes the remainder
    so the shares always add up to exactly the item's qty, gross and
    discount."""
    weights = [Decimal(q) for q in batch_quantities]
    quantities = [money(Decimal(qty) * w / base_qty) for w in weights[:-1]]
    quantities.append(Decimal(qty) - sum(quantities, ZERO))
    return list(zip(quantities, split(gross, weights), split(discount, weights)))


# --- Prescriptions --------------------------------------------------------

@dataclass(frozen=True)
class Prescription:
    """Who medicine needing a prescription was sold to and on whose
    prescription. Every part is optional (the shop's choice)."""
    patient_name: str = ''
    prescriber_name: str = ''
    prescription_ref: str = ''

    @classmethod
    def from_input(cls, patient_name, prescriber_name, prescription_ref):
        """Stripped and cut to the lengths the sale stores."""
        return cls((patient_name or '').strip()[:255], (prescriber_name or '').strip()[:255],
                   (prescription_ref or '').strip()[:64])

    @classmethod
    def of_sale(cls, sale):
        return cls(sale.patient_name, sale.prescriber_name, sale.prescription_ref)


# --- End of shift ---------------------------------------------------------

def z_report(*, opening_float, completed, voided, repayments, is_open, expected_cash_at_close, counted_cash):
    """The Z-report of one shift from its already-loaded sales and credit
    repayments: totals by payment method, VAT, discounts, voids, credit
    repayments taken at the till, and the cash the drawer should hold.
    Voided sales are listed but never counted as takings.

    Once the shift is closed, `expected_cash_at_close` is the figure the
    drawer was counted against (the snapshot taken at close), so expected,
    counted and variance always agree with each other and with every
    report built from the snapshot. Anything that changes the drawer's
    cash after the count (an offline sale synced late, a void, a voided
    repayment) is shown as `changed_after_close` instead of silently
    rewriting the reconciliation."""
    by_method = payment_rows(entry for sale in completed for entry in sale.payment_split())
    repayment_rows = payment_rows(
        (p.payment_method.name, p.payment_method.implementation, p.amount) for p in repayments)

    cash_sales, cash_repayments = cash_total(by_method), cash_total(repayment_rows)
    expected_cash = opening_float + cash_sales + cash_repayments
    changed_after_close = ZERO
    if not is_open and expected_cash_at_close is not None:
        changed_after_close = expected_cash - expected_cash_at_close
        expected_cash = expected_cash_at_close
    return {
        'sales_count': len(completed),
        'gross_total': money(sum((s.total for s in completed), ZERO)),
        'vat_total': money(sum((s.vat_total for s in completed), ZERO)),
        'discount_total': money(sum((s.discount_total for s in completed), ZERO)),
        'by_payment_method': [{**r, 'total': money(r['total'])} for r in by_method.values()],
        'credit_repayments': [{**r, 'total': money(r['total'])} for r in repayment_rows.values()],
        'void_count': len(voided),
        'void_total': money(sum((s.total for s in voided), ZERO)),
        'opening_float': money(opening_float),
        'cash_sales': money(cash_sales),
        'cash_repayments': money(cash_repayments),
        'expected_cash': money(expected_cash),
        'changed_after_close': money(changed_after_close),
        'counted_cash': None if counted_cash is None else money(counted_cash),
        'variance': None if counted_cash is None else money(counted_cash - expected_cash),
    }
