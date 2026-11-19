"""Customer credit use cases: taking and voiding repayments, and a
customer's statement. The models hold the data and what a customer owes
(with_balances); these functions change it."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.permissions import is_store_manager
from payments.models import PaymentMethod
from pos.models import Sale, Shift

from .models import CreditError, CustomerPayment


@transaction.atomic
def receive_payment(*, customer, store, amount, payment_method, user, reference='', note=''):
    """Records a repayment. Taken by a cashier with an open shift at
    `store`, it belongs to that shift (and its cash to that drawer)."""
    if customer.entity_id != store.entity_id:
        raise CreditError(gettext("That customer is not one of this shop's customers."))
    if amount <= 0:
        raise CreditError(gettext('The amount paid must be more than 0.'))
    if not payment_method.is_active_for(store.entity_id):
        raise CreditError(gettext('{name} is not enabled.').format(name=payment_method.name))
    reference = (reference or '').strip()
    if payment_method.requires_reference and not reference:
        raise CreditError(gettext('Enter the {name} transaction reference.').format(name=payment_method.name))
    # Locked so a repayment and the shift's close cannot interleave: the
    # cash is in the drawer count, or it waits for the next shift.
    shift = Shift.open_for(store=store, cashier=user).select_for_update().first()
    if payment_method.implementation == PaymentMethod.Implementation.CASH and shift is None \
            and not is_store_manager(user, store):
        raise CreditError(gettext('Open a shift to take a cash payment, so it is counted in your drawer.'))
    return CustomerPayment.objects.create(
        customer=customer, store=store, shift=shift, amount=amount, payment_method=payment_method,
        reference=reference[:64], note=(note or '').strip()[:255], received_by=user,
    )


@transaction.atomic
def void_payment(payment, *, user, reason):
    """Reverses a repayment, which puts the amount back on the customer's
    balance. The caller checks that `user` may."""
    locked = CustomerPayment.objects.select_for_update().get(pk=payment.pk)
    if locked.voided_at is not None:
        raise CreditError(gettext('This payment is already voided.'))
    reason = (reason or '').strip()
    if not reason:
        raise CreditError(gettext('Give a reason for voiding this payment.'))
    locked.voided_at, locked.voided_by, locked.void_reason = timezone.now(), user, reason[:255]
    locked.save(update_fields=['voided_at', 'voided_by', 'void_reason'])
    payment.refresh_from_db()


def statement(customer):
    """(rows, balance): every credit sale and payment of `customer`, oldest
    first, each with the running balance — what to show (or print) when
    they come to settle up. Voided rows are listed but not counted."""
    rows = []
    sales = (customer.sales.filter(status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED], credit_amount__gt=0)
             .select_related('store'))
    for sale in sales:
        rows.append({
            'kind': 'sale', 'id': str(sale.id), 'date': sale.completed_at, 'store': sale.store.name,
            'description': gettext('Receipt #{number}').format(number=sale.number), 'amount': sale.credit_amount,
            'voided': sale.status == Sale.Status.VOIDED,
        })
    for payment in customer.payments.select_related('store', 'payment_method'):
        rows.append({
            'kind': 'payment', 'id': str(payment.id), 'date': payment.created_at, 'store': payment.store.name,
            'description': gettext('Paid by {method}').format(method=gettext(payment.payment_method.name))
                           + (f' ({payment.reference})' if payment.reference else ''),
            'amount': -payment.amount, 'voided': payment.voided_at is not None,
        })
    rows.sort(key=lambda r: r['date'] or timezone.now())
    balance = Decimal('0')
    for row in rows:
        if not row['voided']:
            balance += row['amount']
        row['balance'] = balance
    return rows, balance
