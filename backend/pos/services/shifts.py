"""Opening and closing a cashier's shift, and its end-of-day (Z) report."""

from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext

from core.money import money
from credit.models import CustomerPayment

from ..domain import z_report
from ..errors import SaleError
from ..models import Sale, Shift


def check_can_open(store, cashier):
    """Refuses a second open shift for the same cashier at one store."""
    if Shift.open_for(store=store, cashier=cashier).exists():
        raise SaleError(gettext('You already have an open shift at this store.'))


def with_summary_data(queryset):
    """`queryset` of shifts with everything summary() reads prefetched, so
    a list of shifts costs a fixed number of queries instead of three each."""
    return queryset.prefetch_related(
        models.Prefetch('sales', queryset=Sale.objects.filter(
            status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED],
        ).select_related('payment_method', 'customer').prefetch_related('lines'), to_attr='_summary_sales'),
        models.Prefetch('credit_payments', queryset=CustomerPayment.objects.filter(
            voided_at__isnull=True,
        ).select_related('payment_method'), to_attr='_summary_payments'),
    )


def _summary_inputs(shift):
    """(completed sales, voided sales, unvoided credit repayments): from
    with_summary_data()'s prefetch when there is one, else queried."""
    if hasattr(shift, '_summary_sales'):
        sales = shift._summary_sales
        completed = [s for s in sales if s.status == Sale.Status.COMPLETED]
        voided = [s for s in sales if s.status == Sale.Status.VOIDED]
        return completed, voided, shift._summary_payments
    completed = list(shift.sales.filter(status=Sale.Status.COMPLETED)
                     .select_related('payment_method', 'customer').prefetch_related('lines'))
    voided = list(shift.sales.filter(status=Sale.Status.VOIDED).prefetch_related('lines'))
    payments = list(shift.credit_payments.filter(voided_at__isnull=True).select_related('payment_method'))
    return completed, voided, payments


def summary(shift):
    """The shift's Z-report (see pos.domain.z_report)."""
    completed, voided, repayments = _summary_inputs(shift)
    return z_report(
        opening_float=shift.opening_float, completed=completed, voided=voided, repayments=repayments,
        is_open=shift.is_open, expected_cash_at_close=shift.expected_cash, counted_cash=shift.counted_cash,
    )


@transaction.atomic
def close(shift, *, counted_cash, note=''):
    """Closes the shift and returns its final Z-report, built once: the
    drawer count only adds the counted cash and the difference to what the
    report already showed.

    The shift row is locked first, so a double-tapped Close (or a manager
    closing it from another device at the same time) closes it once and
    refuses the other, instead of overwriting the first count; and a sale
    or repayment being taken in this shift either lands before the count
    or is refused (see checkout._selling_shift)."""
    locked = Shift.objects.select_for_update().get(pk=shift.pk)
    if not locked.is_open:
        raise SaleError(gettext('This shift is already closed.'))
    z = summary(locked)
    locked.expected_cash = z['expected_cash']
    locked.counted_cash = counted_cash
    locked.closing_note = note
    locked.closed_at = timezone.now()
    locked.save(update_fields=['expected_cash', 'counted_cash', 'closing_note', 'closed_at'])
    shift.refresh_from_db()
    return {**z, 'counted_cash': money(counted_cash), 'variance': money(counted_cash - locked.expected_cash)}
