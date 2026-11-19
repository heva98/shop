import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext, gettext_lazy

from catalog.models import Product
from core.models import Store
from core.money import ZERO, money, vat_portion
from payments.models import PaymentMethod

from .domain import discount_over_limit, split_payment
from .errors import SaleError

__all__ = ['Sale', 'SaleError', 'SaleLine', 'Shift', 'split_payment']

# The data of selling and what follows from it alone (totals, VAT, how a
# sale was paid). Everything that changes a sale or a shift — pricing a
# cart, completing, voiding, closing a shift — is in pos.services.

class Shift(models.Model):
    """One cashier's session at one till: opens with a counted float,
    closes with a counted drawer. Every completed sale belongs to the
    shift it was rung up in, which is what the end-of-day (Z) report and
    cash reconciliation are computed from."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='shifts')
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='shifts')
    opened_at = models.DateTimeField(auto_now_add=True)
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closed_at = models.DateTimeField(null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_cash = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Snapshot taken at close: opening float + cash sales + cash credit repayments.',
    )
    closing_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'cashier'], condition=Q(closed_at__isnull=True),
                name='one_open_shift_per_cashier_per_store',
            ),
        ]

    def __str__(self):
        return f'Shift {self.cashier} @ {self.store} {self.opened_at:%Y-%m-%d %H:%M}'

    @property
    def is_open(self):
        return self.closed_at is None

    @classmethod
    def open_for(cls, *, store, cashier):
        """The cashier's open shift at the store (at most one, see the
        constraint above), as a queryset: .first() / .exists()."""
        return cls.objects.filter(store=store, cashier=cashier, closed_at__isnull=True)



class Sale(models.Model):
    """Walk-in POS sale to an external customer only — inter-store movement
    goes through enquiry.Transfer instead, paid or not, since that never
    needs fiscal receipting.

    Lifecycle: open (cart being built, nothing deducted) -> completed
    (stock deducted, paid, numbered, locked) -> voided (manager-approved
    reversal; stock goes back to the same batches). A completed sale is
    never edited or deleted — corrections are voids, so the record of what
    happened is kept.

    Part or all of a sale can be put on a registered customer's account
    (credit_amount, see credit.Customer): the payment method then only
    covers the rest, and the customer owes the credit part until they pay
    it off with a credit.CustomerPayment."""

    class Status(models.TextChoices):
        OPEN = 'open', gettext_lazy('Open')
        COMPLETED = 'completed', gettext_lazy('Completed')
        VOIDED = 'voided', gettext_lazy('Voided')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name='sales')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    number = models.PositiveIntegerField(
        null=True, blank=True, help_text='Sequential receipt number per store, assigned on completion.',
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='sales',
    )
    shift = models.ForeignKey(Shift, null=True, blank=True, on_delete=models.PROTECT, related_name='sales')
    payment_method = models.ForeignKey(
        PaymentMethod, null=True, blank=True, on_delete=models.PROTECT, related_name='sales',
    )
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment_reference = models.CharField(
        max_length=64, blank=True, help_text='Mobile money / bank transaction reference.',
    )
    customer = models.ForeignKey(
        'credit.Customer', null=True, blank=True, on_delete=models.PROTECT, related_name='sales',
        help_text='A registered customer: required for a credit sale, optional otherwise.',
    )
    credit_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="The share of the total put on the customer's account instead of paid now.")
    customer_name = models.CharField(max_length=255, blank=True, help_text='Printed on the receipt.')
    # Pharmacies: required when the sale has prescription-only or controlled
    # medicine (Product.needs_prescription), and copied into the controlled
    # drugs register (controlled_substances).
    patient_name = models.CharField(max_length=255, blank=True)
    prescriber_name = models.CharField(max_length=255, blank=True, help_text='The doctor or clinic on the prescription.')
    prescription_ref = models.CharField(max_length=64, blank=True, help_text='Prescription number, if any.')
    discount_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text="The manager who allowed a discount above the cashier's limit.",
    )
    efd_receipt_no = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    void_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'number'], condition=Q(number__isnull=False), name='unique_sale_number_per_store',
            ),
        ]
        indexes = [
            # A store's completed sales over a date range: what a manager asks
            # Analytics most ("this week at my store"). Measured on 650k sales:
            # 170 ms → 105 ms; long ranges read most rows anyway and don't use it.
            models.Index(fields=['store', 'completed_at'], condition=Q(status='completed'),
                         name='sale_store_completed'),
        ]

    def __str__(self):
        return f'Sale #{self.number or "—"} @ {self.store}'

    @property
    def total(self):
        return sum((line.line_total for line in self.lines.all()), start=ZERO)

    @property
    def discount_total(self):
        return sum((line.discount for line in self.lines.all()), start=ZERO)

    @property
    def vat_total(self):
        """Shelf prices are VAT-inclusive, so the VAT is the 18/118 share
        of every standard-rated line (after its discount)."""
        return money(sum(
            (vat_portion(line.line_total)
             for line in self.lines.all() if line.vat_class == Product.VatClass.STANDARD),
            start=ZERO,
        ))

    @property
    def paid_amount(self):
        """What the customer paid at the till: the total, less any share
        put on their account."""
        return self.total - self.credit_amount

    @property
    def change_due(self):
        if self.amount_tendered is None:
            return None
        return money(self.amount_tendered - self.paid_amount)

    def payment_split(self, total=None):
        """[(name, implementation, amount)]: how the sale was paid. The part
        paid now goes to the payment method and the credit part to the
        customer's account. Pass `total` when it is already known."""
        total = self.total if total is None else total
        return split_payment(self.payment_method.name, self.payment_method.implementation, total, self.credit_amount)

    def discount_check(self):
        """(discount, gross, limit, over_limit) for the discount on this sale:
        whether it is more than the entity's cashier_discount_limit (a
        percentage of the gross). The one place that rule is written, for
        enforcing it at the till and for auditing it afterwards."""
        discount = self.discount_total
        gross = self.total + discount
        limit = self.store.entity.cashier_discount_limit
        return discount, gross, limit, discount_over_limit(discount, gross, limit)

    def require_status(self, status, action):
        """Refuses `action` (worded for the message) unless the sale is in
        `status`: a completed sale is never changed, an open one never
        voided."""
        if self.status != status:
            raise SaleError(gettext('Cannot {action} a sale that is {lower}.').format(action=action, lower=self.get_status_display().lower()))



class SaleLine(models.Model):
    """`qty` is always in the product's own unit — what came off the batch.
    `sell_qty` / `sell_uom` / `unit_price` are what the customer bought
    (e.g. 2 Crates at 18,000), `discount` what was taken off, and `amount`
    the stored line value after the discount that every total and report
    sums."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='lines')
    batch = models.ForeignKey('inventory.StockBatch', on_delete=models.PROTECT, related_name='+')
    qty = models.DecimalField(max_digits=12, decimal_places=2, help_text="In the product's own unit.")
    sell_uom = models.ForeignKey(
        'catalog.UnitOfMeasure', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text="Null = sold in the product's own unit.",
    )
    sell_qty = models.DecimalField(max_digits=12, decimal_places=2, help_text='In the unit sold.')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text='Per unit sold, before discount.')
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2, help_text='After the discount.')
    vat_class = models.CharField(max_length=10)

    def __str__(self):
        return f'{self.batch} x{self.qty}'

    def save(self, *args, **kwargs):
        if self.sell_qty is None:
            self.sell_qty = self.qty
        if self.amount is None:
            self.amount = money(self.unit_price * self.sell_qty) - (self.discount or 0)
        super().save(*args, **kwargs)

    @property
    def line_total(self):
        return self.amount

    @property
    def gross_amount(self):
        return self.amount + self.discount

    @property
    def unit_name(self):
        return (self.sell_uom or self.batch.product.uom).name

    @property
    def description(self):
        return f'{self.batch.product.name} ({self.sell_uom.name})' if self.sell_uom_id else self.batch.product.name
