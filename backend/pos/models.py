import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy

from catalog.models import Product, convert_qty, sell_unit
from core import features
from core.models import Store
from core.money import ZERO, money, split, vat_portion
from fiscal.drivers.manual_efd import get_fiscal_driver
from fiscal.interfaces import FiscalSaleLine, FiscalSubmission
from fiscal.models import FiscalReceipt
from inventory.models import StockBatch, StockLedger, allocate_fefo
from payments.models import PaymentMethod


class SaleError(Exception):
    """A business rule refused the request (wrong sale status, missing
    payment details, no shift open, ...). Mapped to HTTP 400 by
    config.exceptions.custom_exception_handler, same as
    InsufficientStockError."""


def _payment_rows(entries):
    """{method name: {payment_method, implementation, count, total}} from
    (name, implementation, amount) triples."""
    rows = {}
    for name, implementation, amount in entries:
        row = rows.setdefault(name, {'payment_method': name, 'implementation': implementation, 'count': 0, 'total': ZERO})
        row['count'] += 1
        row['total'] += amount
    return rows


def _customer_payments():
    # credit.models imports this module, so CustomerPayment is looked up late.
    from credit.models import CustomerPayment

    return CustomerPayment.objects.all()


def _cash_total(rows):
    return sum((r['total'] for r in rows.values() if r['implementation'] == PaymentMethod.Implementation.CASH), ZERO)


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

    @classmethod
    def with_summary_data(cls, queryset):
        """`queryset` with everything summary() reads prefetched, so a list
        of shifts costs a fixed number of queries instead of three each."""
        return queryset.prefetch_related(
            models.Prefetch('sales', queryset=Sale.objects.filter(
                status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED],
            ).select_related('payment_method', 'customer').prefetch_related('lines'), to_attr='_summary_sales'),
            models.Prefetch('credit_payments', queryset=_customer_payments().filter(
                voided_at__isnull=True,
            ).select_related('payment_method'), to_attr='_summary_payments'),
        )

    def _summary_inputs(self):
        """(completed sales, voided sales, unvoided credit repayments): from
        with_summary_data()'s prefetch when there is one, else queried."""
        if hasattr(self, '_summary_sales'):
            sales = self._summary_sales
            completed = [s for s in sales if s.status == Sale.Status.COMPLETED]
            voided = [s for s in sales if s.status == Sale.Status.VOIDED]
            return completed, voided, self._summary_payments
        completed = list(self.sales.filter(status=Sale.Status.COMPLETED)
                         .select_related('payment_method', 'customer').prefetch_related('lines'))
        voided = list(self.sales.filter(status=Sale.Status.VOIDED).prefetch_related('lines'))
        payments = list(self.credit_payments.filter(voided_at__isnull=True).select_related('payment_method'))
        return completed, voided, payments

    def summary(self):
        """The Z-report: totals by payment method, VAT, discounts, voids,
        credit repayments taken at the till, and the cash the drawer should
        hold. Voided sales are listed but never counted as takings.

        Once the shift is closed, `expected_cash` is the figure the drawer
        was counted against (the snapshot taken at close), so expected,
        counted and variance always agree with each other and with every
        report built from the snapshot. Anything that changes the drawer's
        cash after the count (an offline sale synced late, a void, a
        voided repayment) is shown as `changed_after_close` instead of
        silently rewriting the reconciliation."""
        completed, voided, payments = self._summary_inputs()
        by_method = _payment_rows(entry for sale in completed for entry in sale.payment_split())
        repayments = _payment_rows(
            (p.payment_method.name, p.payment_method.implementation, p.amount) for p in payments)

        cash_sales, cash_repayments = _cash_total(by_method), _cash_total(repayments)
        expected_cash = self.opening_float + cash_sales + cash_repayments
        changed_after_close = ZERO
        if not self.is_open and self.expected_cash is not None:
            changed_after_close = expected_cash - self.expected_cash
            expected_cash = self.expected_cash
        return {
            'sales_count': len(completed),
            'gross_total': money(sum((s.total for s in completed), ZERO)),
            'vat_total': money(sum((s.vat_total for s in completed), ZERO)),
            'discount_total': money(sum((s.discount_total for s in completed), ZERO)),
            'by_payment_method': [{**r, 'total': money(r['total'])} for r in by_method.values()],
            'credit_repayments': [{**r, 'total': money(r['total'])} for r in repayments.values()],
            'void_count': len(voided),
            'void_total': money(sum((s.total for s in voided), ZERO)),
            'opening_float': money(self.opening_float),
            'cash_sales': money(cash_sales),
            'cash_repayments': money(cash_repayments),
            'expected_cash': money(expected_cash),
            'changed_after_close': money(changed_after_close),
            'counted_cash': None if self.counted_cash is None else money(self.counted_cash),
            'variance': None if self.counted_cash is None else money(self.counted_cash - expected_cash),
        }

    @transaction.atomic
    def close(self, *, counted_cash, note=''):
        """Closes the shift and returns its final Z-report (summary()),
        built once: the drawer count only adds the counted cash and the
        difference to what the report already showed.

        The shift row is locked first, so a double-tapped Close (or a
        manager closing it from another device at the same time) closes it
        once and refuses the other, instead of overwriting the first count;
        and a sale or repayment being taken in this shift either lands
        before the count or is refused (see Sale._selling_shift)."""
        locked = Shift.objects.select_for_update().get(pk=self.pk)
        if not locked.is_open:
            raise SaleError(gettext('This shift is already closed.'))
        z = locked.summary()
        locked.expected_cash = z['expected_cash']
        locked.counted_cash = counted_cash
        locked.closing_note = note
        locked.closed_at = timezone.now()
        locked.save(update_fields=['expected_cash', 'counted_cash', 'closing_note', 'closed_at'])
        self.refresh_from_db()
        return {**z, 'counted_cash': money(counted_cash), 'variance': money(counted_cash - locked.expected_cash)}


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
        parts = []
        if total - self.credit_amount > 0 or not self.credit_amount:
            parts.append((self.payment_method.name, self.payment_method.implementation, total - self.credit_amount))
        if self.credit_amount:
            parts.append((gettext('On credit'), 'credit', self.credit_amount))
        return parts

    def discount_check(self):
        """(discount, gross, limit, over_limit) for the discount on this sale:
        whether it is more than the entity's cashier_discount_limit (a
        percentage of the gross). The one place that rule is written, for
        enforcing it at the till and for auditing it afterwards."""
        discount = self.discount_total
        gross = self.total + discount
        limit = self.store.entity.cashier_discount_limit
        return discount, gross, limit, bool(discount) and discount * 100 > gross * limit

    def _require_status(self, status, action):
        if self.status != status:
            raise SaleError(gettext('Cannot {action} a sale that is {lower}.').format(action=action, lower=self.get_status_display().lower()))

    def current_price(self, product, uom=None):
        """The store's selling price today for one `uom` of `product`
        (default: its own unit) — a running promotion's price if there is
        one — or None when no price is set."""
        from pricing.models import effective_price

        return effective_price(store=self.store, product=product, uom=uom)[0]

    @transaction.atomic
    def add_product(self, *, product, qty, uom=None, unit_price=None, discount=ZERO, allow_shortfall=False):
        """Adds qty of product, in `uom` (default: the product's own unit),
        to the cart at the store's own selling price for that unit
        (pricing.Price, or a running pricing.Promotion — never a price sent
        by the till), less `discount` off the whole item. Stock is
        allocated FEFO in the product's own unit, splitting across batches
        if one alone doesn't cover it. Raises InsufficientStockError if the
        store doesn't have enough on hand.

        `unit_price` is only for recording a sale the till already made
        offline (see record_offline): the price the customer was charged
        then, which the cloud may have changed since. `allow_shortfall`
        (offline sales only) records the item even when the system shows
        too little stock, since the goods were sold: see allocate_fefo."""
        self._require_status(self.Status.OPEN, gettext('add items to'))
        if product.entity_id != self.store.entity_id:
            raise SaleError(gettext("Product is not in this shop's catalog."))
        if product.is_controlled_substance and not features.is_enabled('controlled_substances_register', store=self.store):
            raise SaleError(gettext('{name} is a controlled drug, and {store} is not set up to sell them. An owner can switch on the controlled drugs register under Settings > Features.').format(name=product.name, store=self.store.name))
        sell_uom = sell_unit(product, uom)
        if sell_uom is not None and sell_uom.entity_id != product.entity_id:
            raise SaleError(gettext("Unit is not in this shop's catalog."))
        if unit_price is None:
            unit_price = self.current_price(product, sell_uom)
        if unit_price is None:
            unit = f' per {sell_uom.name}' if sell_uom else ''
            raise SaleError(
                gettext('{name} has no selling price{unit} set. Ask a manager to set one under Settings > Selling prices.').format(name=product.name, unit=unit))
        gross = money(unit_price * qty)
        discount = money(discount or 0)
        if discount < 0 or discount > gross:
            raise SaleError(gettext('The discount on {name} must be between 0 and TZS {gross:,.0f}.').format(name=product.name, gross=gross))

        base_qty = convert_qty(qty, sell_uom, product.uom)
        # Stock comes off only when the sale is completed, so units earlier
        # lines of this cart planned on are still on hand: reserve them.
        reserved = dict(self.lines.filter(batch__product=product).values('batch_id')
                        .annotate(qty=Sum('qty')).values_list('batch_id', 'qty'))
        plan = allocate_fefo(self.store, product, base_qty, reserved=reserved, allow_shortfall=allow_shortfall)
        # One cart item can be split over several batches; each line gets
        # its share of the quantity, amount and discount, and the last takes
        # the remainder so the lines always add up to exactly qty x price.
        weights = [Decimal(batch_qty) for _, batch_qty in plan]
        quantities = [money(Decimal(qty) * w / base_qty) for w in weights[:-1]]
        quantities.append(Decimal(qty) - sum(quantities, ZERO))
        lines = []
        for (batch, batch_qty), line_qty, line_gross, line_discount in zip(
                plan, quantities, split(gross, weights), split(discount, weights)):
            lines.append(SaleLine.objects.create(
                sale=self, batch=batch, qty=batch_qty, sell_uom=sell_uom, sell_qty=line_qty,
                unit_price=unit_price, discount=line_discount, amount=line_gross - line_discount,
                vat_class=product.vat_class,
            ))
        return lines

    @classmethod
    @transaction.atomic
    def record_offline(cls, *, id, store, user, items, strict=False, shift=None, completed_at=None,
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
        sale = cls.objects.create(id=id, store=store, cashier=user)
        price_changes = []
        for item in items:
            product, uom, charged = item['product'], item.get('uom'), item['unit_price']
            price = sale.current_price(product, sell_unit(product, uom))
            if price is not None and price != charged:
                if strict:
                    raise SaleError(
                        gettext('The price of {name} has changed to TZS {price:,.0f}. The cart now shows the new price: check the total with the customer.').format(name=product.name, price=price))
                price_changes.append({'product': product.name, 'charged': charged, 'current': price})
            sale.add_product(product=product, qty=item['qty'], uom=uom, unit_price=None if strict else charged,
                             discount=item.get('discount') or ZERO, allow_shortfall=not strict)
        result = sale.complete(user=user, shift=shift, completed_at=completed_at, enforce_limits=strict, **payment)
        if efd_receipt_no:
            # A duplicate or mistyped number must not lose the sale: it can
            # be entered again from the shift's sales list.
            try:
                with transaction.atomic():
                    sale.record_fiscal_receipt(receipt_number=efd_receipt_no, user=user)
            except SaleError:
                pass
        return sale, result, price_changes

    @transaction.atomic
    def remove_product(self, product):
        self._require_status(self.Status.OPEN, gettext('remove items from'))
        self.lines.filter(batch__product=product).delete()

    def _apply_sale_discount(self, discount):
        """A discount off the whole sale, shared over the lines in
        proportion to their amounts so every line (and the VAT on it)
        reflects what was really charged."""
        discount = money(discount)
        lines = list(self.lines.all())
        total = sum((line.amount for line in lines), ZERO)
        if discount < 0 or discount > total:
            raise SaleError(gettext('The discount must be between 0 and TZS {total:,.0f}.').format(total=total))
        for line, share in zip(lines, split(discount, [line.amount for line in lines])):
            line.discount += share
            line.amount -= share
            line.save(update_fields=['discount', 'amount'])

    def _check_discount_limit(self, user, approver):
        """Returns the manager who approved the discount, if one was needed.
        Raises if the discount is over the cashier's limit and nobody with
        the authority gave it."""
        from core.permissions import is_store_manager

        discount, _gross, limit, over_limit = self.discount_check()
        if not over_limit or is_store_manager(user, self.store):
            return None
        if approver is not None and is_store_manager(approver, self.store):
            return approver
        raise SaleError(gettext('A discount of TZS {discount:,.0f} is more than the {normalize:f}% a cashier may give. A manager must approve it.').format(discount=discount, normalize=limit.normalize()))

    def _check_credit(self, customer, credit_amount, total, enforce_limit):
        if customer is not None and (customer.entity_id != self.store.entity_id or not customer.is_active):
            raise SaleError(gettext("Choose one of the shop's active customers."))
        if not credit_amount:
            return
        if not features.is_enabled('customer_credit', store=self.store):
            raise SaleError(gettext('{name} does not sell on credit. An admin can switch it on under Settings > Features.').format(name=self.store.name))
        if customer is None:
            raise SaleError(gettext('Choose the customer this sale is on credit to.'))
        if credit_amount < 0 or credit_amount > total:
            raise SaleError(gettext('The amount on credit must be between 0 and the total of TZS {total:,.0f}.').format(total=total))
        if enforce_limit and customer.credit_limit is not None:
            owing = customer.balance()
            if owing + credit_amount > customer.credit_limit:
                raise SaleError(
                    gettext('{name} already owes TZS {owing:,.0f}; their credit limit is TZS {credit_limit:,.0f}. Take at most TZS {max:,.0f} on credit.').format(name=customer.name, owing=owing, credit_limit=customer.credit_limit, max=max(customer.credit_limit - owing, 0)))

    def _check_prescription(self, user, patient_name, prescriber_name, prescription_ref):
        """(patient, prescriber, reference), stripped, for medicine that
        needs a prescription (all optional). Empty for any other sale."""
        products = {line.batch.product for line in self.lines.select_related('batch__product')}
        if not any(p.needs_prescription for p in products):
            return '', '', ''
        patient, prescriber = (patient_name or '').strip(), (prescriber_name or '').strip()
        return patient[:255], prescriber[:255], (prescription_ref or '').strip()[:64]

    def _register(self, ledger_entry, line, user, rx, *, returned):
        from controlled_substances.models import ControlledSubstanceEntry

        ControlledSubstanceEntry.objects.create(
            store=self.store, product=line.batch.product, ledger_entry=ledger_entry, sale=self,
            kind=ControlledSubstanceEntry.Kind.RETURNED if returned else ControlledSubstanceEntry.Kind.DISPENSED,
            qty=-line.qty if returned else line.qty, batch_no=line.batch.batch_no,
            patient_name=rx[0], prescriber_name=rx[1], prescription_ref=rx[2], dispensed_by=user,
        )

    @transaction.atomic
    def complete(self, *, user, payment_method, amount_tendered=None, payment_reference='',
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
        are optional (the shop's choice), kept on the sale and copied into
        the controlled drugs register with whoever sold it. Anyone who
        can sell may sell a controlled drug, cashiers included (the shop's
        choice); the store must have the register switched on.

        `shift` and `completed_at` are for a sale the till recorded
        offline: the cashier's shift it was rung up in (even if closed
        since) and when it happened. Default: the open shift, now."""
        locked = Sale.objects.select_for_update().select_related('store__entity').get(pk=self.pk)
        locked._require_status(self.Status.OPEN, 'complete')
        if not locked.lines.exists():
            raise SaleError(gettext('The cart is empty.'))
        shift = locked._selling_shift(user, shift, allow_closed=not enforce_limits)
        now = timezone.now()
        completed_at = now if completed_at is None or completed_at > now else completed_at
        rx = locked._check_prescription(user, patient_name, prescriber_name, prescription_ref)

        # The checks run in this order so the cashier sees the same first
        # problem whichever way the sale arrives.
        if not payment_method.is_active_for(locked.store.entity_id):
            raise SaleError(gettext('{name} is not enabled.').format(name=payment_method.name))
        if discount:
            locked._apply_sale_discount(discount)
        approved_by = locked._check_discount_limit(user, discount_approver) if enforce_limits else None
        total = locked.total
        credit_amount = money(credit_amount or 0)
        locked._check_credit(customer, credit_amount, total, enforce_limits)
        amount_tendered, payment_reference = locked._check_payment(
            payment_method, total - credit_amount, amount_tendered, payment_reference)

        locked._deduct_stock(user, rx, allow_shortfall=not enforce_limits)
        locked.status = self.Status.COMPLETED
        locked.number = locked._next_number()
        locked.cashier = user
        locked.shift = shift
        locked.payment_method = payment_method
        locked.amount_tendered = amount_tendered
        locked.payment_reference = payment_reference
        locked.customer = customer
        locked.credit_amount = credit_amount
        locked.customer_name = (customer.name if customer is not None else (customer_name or '').strip())[:255]
        locked.discount_approved_by = approved_by
        locked.patient_name, locked.prescriber_name, locked.prescription_ref = rx
        locked.completed_at = completed_at
        locked.save()
        self.refresh_from_db()
        return self.retry_fiscal()

    def _selling_shift(self, user, shift, *, allow_closed):
        """`shift` when it is the user's own at this store, else the user's
        open shift here. Refuses when there is neither.

        A closed `shift` is only taken when `allow_closed`: an offline sale
        was rung up in it before it closed and still belongs to it. A sale
        being made now must not go into a closed shift, whose drawer has
        already been counted; it goes to the open one or is refused.

        The shift row is locked, so a sale and the shift's close cannot
        interleave: the sale is in the count, or it sees the shift closed."""
        named = None
        if shift is not None and shift.store_id == self.store_id and shift.cashier_id == user.pk:
            named = Shift.objects.select_for_update().filter(pk=shift.pk).first()
            if named is not None and not named.is_open and not allow_closed:
                named = None
        shift = named or Shift.open_for(store=self.store, cashier=user).select_for_update().first()
        if shift is None:
            raise SaleError(gettext('Open a shift before selling.'))
        return shift

    @staticmethod
    def _check_payment(payment_method, payable, amount_tendered, payment_reference):
        """(amount_tendered, payment_reference) to record. Cash must cover
        what is payable and carries no reference; any other method needs a
        transaction reference and is taken for exactly the amount due."""
        if payment_method.implementation == PaymentMethod.Implementation.CASH:
            if payable == 0 and amount_tendered is None:
                amount_tendered = Decimal('0')
            if amount_tendered is None or amount_tendered < payable:
                raise SaleError(gettext('Amount tendered must cover the total of TZS {payable:,.0f}.').format(payable=payable))
            return amount_tendered, ''
        payment_reference = (payment_reference or '').strip()
        if payable > 0 and not payment_reference:
            raise SaleError(gettext('Enter the {name} transaction reference.').format(name=payment_method.name))
        return payable, payment_reference

    def _deduct_stock(self, user, rx, *, allow_shortfall):
        """Takes every line off its batch, and enters controlled drugs in
        the register with the prescription details `rx`.

        `allow_shortfall` (an offline sale, which already happened): when
        a batch holds less than the line sold, the missing units are first
        put on it as 'sold without recorded stock', so the sale is never
        lost and stock never goes negative. Without it, too little stock
        refuses the whole sale (InsufficientStockError)."""
        for line in self.lines.select_related('batch__product'):
            if allow_shortfall:
                on_hand = StockBatch.objects.select_for_update().get(pk=line.batch_id).qty_on_hand
                if on_hand < line.qty:
                    StockLedger.record(
                        store=self.store, batch=line.batch, qty_delta=line.qty - on_hand,
                        ledger_type=StockLedger.LedgerType.UNRECORDED, ref_type='sale', ref_id=self.id,
                    )
            entry = StockLedger.record(
                store=self.store, batch=line.batch, qty_delta=-line.qty,
                ledger_type=StockLedger.LedgerType.SOLD, ref_type='sale', ref_id=self.id,
            )
            if line.batch.product.is_controlled_substance:
                self._register(entry, line, user, rx, returned=False)

    def _next_number(self):
        """The store's next receipt number. The store row lock serializes
        numbering, so two tills can never be handed the same number."""
        Store.objects.select_for_update().get(pk=self.store_id)
        return (Sale.objects.filter(store_id=self.store_id).aggregate(n=Max('number'))['n'] or 0) + 1

    def retry_fiscal(self):
        """Re-attempts fiscalization only — no stock movement. This is
        what the POS design's 'Retry printing' button drives."""
        self._require_status(self.Status.COMPLETED, 'fiscalize')
        driver = get_fiscal_driver(self.store)
        submission = FiscalSubmission(
            sale_id=str(self.id),
            store_device_id=self.store.efd_device_id,
            lines=[
                FiscalSaleLine(
                    description=line.description, quantity=float(line.sell_qty),
                    unit_price=float(line.amount / line.sell_qty) if line.sell_qty else float(line.unit_price),
                    vat_class=line.vat_class,
                )
                for line in self.lines.select_related('batch__product', 'sell_uom')
            ],
            total=float(self.total),
        )
        result = driver.submit_sale(submission)
        if result.pending_manual:
            return result
        FiscalReceipt.objects.create(
            sale_id=self.id, driver=driver.name,
            receipt_number=result.receipt_number or '',
            status=FiscalReceipt.Status.SUBMITTED if result.success else FiscalReceipt.Status.FAILED,
            error=result.error or '',
        )
        if result.success:
            self.efd_receipt_no = result.receipt_number
            self.save(update_fields=['efd_receipt_no'])
        return result

    @transaction.atomic
    def record_fiscal_receipt(self, *, receipt_number, user):
        """Stores the receipt number printed by a standalone EFD machine."""
        receipt_number = (receipt_number or '').strip()
        if not receipt_number:
            raise SaleError(gettext('Enter the EFD receipt number.'))
        if self.status == self.Status.OPEN:
            raise SaleError(gettext('Complete the sale before recording its EFD receipt.'))
        if self.efd_receipt_no:
            raise SaleError(gettext('EFD receipt {efd_receipt_no} is already recorded for this sale.').format(efd_receipt_no=self.efd_receipt_no))
        if Sale.objects.filter(store=self.store, efd_receipt_no=receipt_number).exclude(pk=self.pk).exists():
            raise SaleError(gettext('EFD receipt {receipt_number} is already recorded on another sale. Check the number.').format(receipt_number=receipt_number))
        FiscalReceipt.objects.create(
            sale_id=self.id, driver=get_fiscal_driver(self.store).name, receipt_number=receipt_number,
            status=FiscalReceipt.Status.RECORDED, entered_by=user,
        )
        self.efd_receipt_no = receipt_number
        self.save(update_fields=['efd_receipt_no'])

    @transaction.atomic
    def void(self, *, user, approver, reason):
        """Reverses a completed sale: every line's quantity goes back to the
        batch it came from (a 'sale_void' ledger entry, so the ledger still
        shows both movements). A credit sale's amount stops counting
        against the customer's balance, since that is computed from
        completed sales only. `approver` must already have been checked
        as a manager for this store by the caller."""
        locked = Sale.objects.select_for_update().get(pk=self.pk)
        locked._require_status(self.Status.COMPLETED, 'void')
        reason = (reason or '').strip()
        if not reason:
            raise SaleError(gettext('Give a reason for voiding this sale.'))
        for line in locked.lines.select_related('batch__product'):
            entry = StockLedger.record(
                store=locked.store, batch=line.batch, qty_delta=line.qty,
                ledger_type=StockLedger.LedgerType.SALE_VOID, ref_type='sale', ref_id=locked.id,
            )
            if line.batch.product.is_controlled_substance:
                rx = (locked.patient_name, locked.prescriber_name, locked.prescription_ref)
                locked._register(entry, line, user, rx, returned=True)
        locked.status = self.Status.VOIDED
        locked.voided_at = timezone.now()
        locked.voided_by = user
        locked.void_approved_by = approver
        locked.void_reason = reason
        locked.save(update_fields=['status', 'voided_at', 'voided_by', 'void_approved_by', 'void_reason'])
        self.refresh_from_db()


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
