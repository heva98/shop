"""Customer credit (madeni): selling to known customers on account and
collecting what they owe.

At the till, part or all of a sale can go on a registered customer's
account (pos.Sale.customer + credit_amount). The customer pays it off
later with a CustomerPayment, at the till (counted in that shift's cash)
or in the back office. What a customer owes is never stored: it is always
worked out from their completed credit sales less their payments, so a
voided sale or a voided payment corrects the balance by itself."""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import Entity, Store
from payments.models import PaymentMethod


class CreditError(Exception):
    """A credit rule refused the request. Mapped to HTTP 400 by
    config.exceptions.custom_exception_handler."""


_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=14, decimal_places=2))


def with_balances(queryset):
    """Customers annotated with `credit_total` (completed credit sales),
    `paid_total` (payments not voided) and `owing` (the difference)."""
    from pos.models import Sale

    credit = (Sale.objects.filter(customer=OuterRef('pk'), status=Sale.Status.COMPLETED)
              .values('customer').annotate(t=Sum('credit_amount')).values('t'))
    paid = (CustomerPayment.objects.filter(customer=OuterRef('pk'), voided_at__isnull=True)
            .values('customer').annotate(t=Sum('amount')).values('t'))
    return queryset.annotate(
        credit_total=Coalesce(Subquery(credit), _ZERO),
        paid_total=Coalesce(Subquery(paid), _ZERO),
    ).annotate(owing=models.F('credit_total') - models.F('paid_total'))


class Customer(models.Model):
    """Entity-wide: a customer who buys on credit at one branch can pay
    at another."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='customers')
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, blank=True, help_text='e.g. 255712345678')
    address = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)
    credit_limit = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='The most the customer may owe at once. Empty = no limit; 0 = no credit.',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'phone'], condition=~models.Q(phone=''), name='unique_customer_phone_per_entity',
            ),
        ]

    def __str__(self):
        return self.name

    def balance(self):
        """What the customer owes now (negative = they paid in advance)."""
        return with_balances(Customer.objects.filter(pk=self.pk)).values_list('owing', flat=True).first() or Decimal('0')


class CustomerPayment(models.Model):
    """Money a customer paid towards what they owe. Never edited or
    deleted: a mistake is voided (with a reason), which puts the amount
    back on the customer's balance."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='payments')
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='credit_payments')
    shift = models.ForeignKey(
        'pos.Shift', null=True, blank=True, on_delete=models.PROTECT, related_name='credit_payments',
        help_text="The till shift it was taken in, so cash repayments count in that drawer's expected cash.",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name='+')
    reference = models.CharField(max_length=64, blank=True, help_text='Mobile money / bank transaction reference.')
    note = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer} paid {self.amount}'

    @classmethod
    @transaction.atomic
    def receive(cls, *, customer, store, amount, payment_method, user, reference='', note=''):
        """Records a payment. Taken by a cashier with an open shift at
        `store`, it belongs to that shift (and its cash to that drawer)."""
        from pos.models import Shift

        if customer.entity_id != store.entity_id:
            raise CreditError('That customer is not one of this shop\'s customers.')
        if amount <= 0:
            raise CreditError('The amount paid must be more than 0.')
        if not payment_method.is_active:
            raise CreditError(f'{payment_method.name} is not enabled.')
        reference = (reference or '').strip()
        if payment_method.requires_reference and not reference:
            raise CreditError(f'Enter the {payment_method.name} transaction reference.')
        shift = Shift.objects.filter(store=store, cashier=user, closed_at__isnull=True).first()
        if payment_method.implementation == PaymentMethod.Implementation.CASH and shift is None \
                and not _is_manager(user, store):
            raise CreditError('Open a shift to take a cash payment, so it is counted in your drawer.')
        return cls.objects.create(
            customer=customer, store=store, shift=shift, amount=amount, payment_method=payment_method,
            reference=reference[:64], note=(note or '').strip()[:255], received_by=user,
        )

    @transaction.atomic
    def void(self, *, user, reason):
        locked = CustomerPayment.objects.select_for_update().get(pk=self.pk)
        if locked.voided_at is not None:
            raise CreditError('This payment is already voided.')
        reason = (reason or '').strip()
        if not reason:
            raise CreditError('Give a reason for voiding this payment.')
        locked.voided_at, locked.voided_by, locked.void_reason = timezone.now(), user, reason[:255]
        locked.save(update_fields=['voided_at', 'voided_by', 'void_reason'])
        self.refresh_from_db()


def _is_manager(user, store):
    from core.permissions import is_store_manager
    return is_store_manager(user, store)
