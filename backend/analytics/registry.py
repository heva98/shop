"""
The analytics registry: every metric, dimension and fact source the Data
Visualizer knows about. Views and the query engine read definitions from
here; no metric is hard-coded anywhere else.

Three kinds of definition:

* **Fact sources**: one queryable table at a fixed grain (a sale line, a
  receiving line, a stock ledger entry...), how it attaches to a period and
  which store it belongs to.
* **Metrics**: a fact source, a function returning the queryset *at fact
  grain*, and a numerator (plus a denominator for ratios). The engine
  aggregates numerator and denominator per output cell and divides at the
  very end, so an average sale value or a margin is always weighted by the
  underlying sales, never an average of averages.
* **Dimensions**: `dx` (data), `pe` (period), `ou` (firm → store) and the
  dynamic ones (product, category, cashier...). Each maps every fact source
  it applies to onto the ORM path (or expression) to group by.

Everything is filtered by the firm's features (core.features), so a switched
off feature's metrics disappear entirely, and by the stores the caller may
see (core.queryset_scoping).

Queries run against the transactional tables directly (architecture.txt
§6): a pre-aggregated store × product × day table couldn't be broken down by
cashier, payment method, supplier or hour, and its stock figures would be a
single snapshot. Sources here are dated, so any period can be asked for, and
stock balances are rebuilt from the ledger as of the end of each period.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Mapping, Union

from django.db.models import (
    Case, CharField, Count, DecimalField, Expression, ExpressionWrapper, F, Q, QuerySet, Sum, Value, When,
)
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from catalog.models import Category, Product
from core.features import FEATURES_BY_KEY, feature_values
from core.models import Store, User
from core.queryset_scoping import accessible_store_ids
from credit.models import Customer, CustomerPayment
from inventory.models import StockLedger
from payments.models import PaymentMethod
from pos.models import Sale, SaleLine, Shift
from receiving.models import ReceivingInvoice, ReceivingInvoiceLine, Supplier, SupplierPayment

from .periods import PERIOD_TYPES, RELATIVE_PERIODS

_DEC = DecimalField(max_digits=18, decimal_places=4)

# A group-by target: an ORM path, or a factory for an expression when the
# value needs a calculation a path can't express.
FieldRef = Union[str, Callable[[], Expression]]


def as_expression(ref: FieldRef) -> Expression:
    return F(ref) if isinstance(ref, str) else ref()


def _dec(expression) -> ExpressionWrapper:
    return ExpressionWrapper(expression, output_field=_DEC)


class Aggregation:
    SUM = 'sum'
    COUNT = 'count'
    COUNT_DISTINCT = 'count_distinct'
    RATIO = 'ratio'
    BALANCE = 'balance'


# ── who is asking ──────────────────────────────────────────────────────────

@dataclass
class Context:
    """The caller as the registry sees them: their firm, its features and
    the stores they may see (None = every store of the firm)."""
    user: object
    entity: object
    features: dict
    store_ids: list | None

    @classmethod
    def for_user(cls, user):
        entity = getattr(user, 'entity', None)
        if entity is None and not user.is_superuser:
            # entity None means "every firm" below, which only a superuser may see.
            raise PermissionDenied('You are not assigned to a shop.')
        ids = accessible_store_ids(user)
        return cls(user, entity, feature_values(entity), None if ids is None else [str(i) for i in ids])

    def stores(self) -> QuerySet:
        qs = Store.objects.filter(entity=self.entity) if self.entity is not None else Store.objects.all()
        if self.store_ids is not None:
            qs = qs.filter(id__in=self.store_ids)
        return qs.order_by('name')

    def feature_on(self, key) -> bool:
        return self.features.get(key, FEATURES_BY_KEY[key].default)

    def entity_filter(self, path: str) -> Q:
        """Restricts a model to the caller's firm through `path` (an ORM path
        to something with an `entity` FK)."""
        if self.entity is None:
            return Q()
        return Q(**{f'{path}entity_id' if path else 'entity_id': self.entity.id})


# ── metric groups ──────────────────────────────────────────────────────────

class MetricGroup:
    SALES = 'sales'
    PROFIT = 'profit'
    PURCHASES = 'purchases'
    STOCK = 'stock'
    CREDIT = 'credit'
    TILLS = 'tills'


GROUP_LABELS = {
    MetricGroup.SALES: 'Sales',
    MetricGroup.PROFIT: 'Profit',
    MetricGroup.PURCHASES: 'Purchases',
    MetricGroup.STOCK: 'Stock',
    MetricGroup.CREDIT: 'Customer credit',
    MetricGroup.TILLS: 'Tills & cash',
}

# The core.features a group needs; a group whose feature is off for the
# whole firm doesn't exist for it.
GROUP_FEATURES = {
    MetricGroup.SALES: ('pos_sale',),
    MetricGroup.PROFIT: ('pos_sale',),
    MetricGroup.PURCHASES: ('receiving_invoice',),
    MetricGroup.STOCK: (),
    MetricGroup.CREDIT: ('pos_sale', 'customer_credit'),
    MetricGroup.TILLS: ('pos_sale',),
}

FEATURE_LABELS = {key: f.label for key, f in FEATURES_BY_KEY.items()}


def group_enabled(group, ctx: Context) -> bool:
    return all(ctx.feature_on(f) for f in GROUP_FEATURES[group])


# ── fact sources ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FactSource:
    id: str
    label: str
    grain: str
    # The date or datetime column that places a fact in a period.
    date: str
    # ORM path to core.Store (no `_id`).
    store: str
    # A balance: a fact counts towards every period that ends after it
    # (stock on hand at the end of the period), not just the one it's in.
    cumulative: bool = False


_SOURCES = [
    FactSource('sales', 'Sales (items sold)', 'sale line', 'sale__completed_at', 'sale__store'),
    FactSource('receipts', 'Sales (receipts)', 'sale', 'completed_at', 'store'),
    FactSource('voids', 'Voided sales', 'sale', 'voided_at', 'store'),
    FactSource('purchases', 'Purchases', 'supplier invoice line', 'invoice__received_date', 'invoice__store'),
    FactSource('supplier_payments', 'Supplier payments', 'payment', 'paid_on', 'invoice__store'),
    FactSource('stock_moves', 'Stock movements', 'ledger entry', 'created_at', 'store'),
    FactSource('stock_balance', 'Stock on hand', 'ledger entry', 'created_at', 'store', cumulative=True),
    FactSource('credit_payments', 'Credit repayments', 'repayment', 'created_at', 'store'),
    FactSource('shifts', 'Shifts', 'shift', 'closed_at', 'store'),
]
SOURCES: dict[str, FactSource] = {s.id: s for s in _SOURCES}


# ── metrics ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    description: str
    group: str
    source: str
    aggregation: str
    # The facts, filtered, one row per fact.
    queryset: Callable[[], QuerySet]
    numerator: Callable[[], object]
    denominator: Callable[[], object] | None = None
    scale: int = 1          # 100 for percentages
    unit: str = 'TZS'       # TZS | count | qty | percent

    def compute(self, numerator, denominator=None):
        """The metric value from its aggregated parts. Division happens here,
        once, after both parts were summed over the whole cell."""
        if numerator is None:
            return None
        num = Decimal(str(numerator))
        if self.denominator is not None:
            if not denominator:
                return None
            return num / Decimal(str(denominator)) * self.scale
        return num * self.scale


def _sale_lines():
    return SaleLine.objects.filter(sale__status=Sale.Status.COMPLETED)


def _receipts():
    return Sale.objects.filter(status=Sale.Status.COMPLETED)


def _voids():
    return Sale.objects.filter(status=Sale.Status.VOIDED)


def _purchase_lines():
    return ReceivingInvoiceLine.objects.filter(invoice__status=ReceivingInvoice.Status.RECEIVED)


def _ledger():
    return StockLedger.objects.all()


def _credit_payments():
    return CustomerPayment.objects.filter(voided_at__isnull=True)


def _closed_shifts():
    return Shift.objects.filter(closed_at__isnull=False, counted_cash__isnull=False)


_LINE_COST = lambda: _dec(F('qty') * F('batch__unit_cost'))  # noqa: E731
_LINE_GROSS = lambda: _dec(F('amount') + F('discount'))  # noqa: E731
_LINE_PROFIT = lambda: _dec(F('amount') - F('qty') * F('batch__unit_cost'))  # noqa: E731
_MOVE_VALUE = lambda: _dec(F('qty_delta') * F('batch__unit_cost'))  # noqa: E731
# Stock written off: lost, stolen, broken, expired, spoiled, discarded, plus
# corrections of wrong entries, which net out against what they correct.
WASTAGE_LEDGER_TYPES = [
    StockLedger.LedgerType.STOLEN,
    StockLedger.LedgerType.LOST,
    StockLedger.LedgerType.DAMAGED,
    StockLedger.LedgerType.EXPIRED,
    StockLedger.LedgerType.COLD_CHAIN_FAILURE,
    StockLedger.LedgerType.WRONG_ENTRY,
    StockLedger.LedgerType.DISCARD,
    StockLedger.LedgerType.DISPOSE,
]
_WASTE = Q(ledger_type__in=WASTAGE_LEDGER_TYPES)

_METRICS = [
    # ── sales ──
    Metric('sales.net', 'Net sales', 'What customers were charged, after discounts, VAT included.',
           MetricGroup.SALES, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum('amount')),
    Metric('sales.gross', 'Sales before discounts', 'Shelf price times quantity, before any discount.',
           MetricGroup.SALES, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum(_LINE_GROSS())),
    Metric('sales.discounts', 'Discounts given', 'Discounts on items and on whole sales.',
           MetricGroup.SALES, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum('discount')),
    Metric('sales.discount_rate', 'Discount rate (%)', 'Discounts as a share of sales before discounts.',
           MetricGroup.SALES, 'sales', Aggregation.RATIO, _sale_lines,
           lambda: Sum('discount'), lambda: Sum(_LINE_GROSS()), scale=100, unit='percent'),
    Metric('sales.vat', 'VAT in sales', 'The 18/118 share of standard-rated sales.',
           MetricGroup.SALES, 'sales', Aggregation.SUM, _sale_lines,
           lambda: Sum(_dec(F('amount') * Value(Decimal('18')) / Value(Decimal('118'))),
                       filter=Q(vat_class=Product.VatClass.STANDARD))),
    Metric('sales.qty', 'Quantity sold', "Units sold, each product counted in its own stock unit.",
           MetricGroup.SALES, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum('qty'), unit='qty'),
    Metric('sales.count', 'Number of sales', 'Completed receipts.',
           MetricGroup.SALES, 'sales', Aggregation.COUNT_DISTINCT, _sale_lines,
           lambda: Count('sale', distinct=True), unit='count'),
    Metric('sales.avg_sale', 'Average sale value', 'Net sales divided by the number of sales.',
           MetricGroup.SALES, 'sales', Aggregation.RATIO, _sale_lines,
           lambda: Sum('amount'), lambda: Count('sale', distinct=True)),
    Metric('sales.products', 'Different products sold', 'Distinct products with at least one sale.',
           MetricGroup.SALES, 'sales', Aggregation.COUNT_DISTINCT, _sale_lines,
           lambda: Count('batch__product', distinct=True), unit='count'),
    Metric('sales.customers', 'Registered customers served', 'Distinct registered customers who bought.',
           MetricGroup.SALES, 'sales', Aggregation.COUNT_DISTINCT, _sale_lines,
           lambda: Count('sale__customer', distinct=True), unit='count'),
    Metric('sales.voids', 'Voided sales', 'Completed sales later voided, counted when voided.',
           MetricGroup.SALES, 'voids', Aggregation.COUNT_DISTINCT, _voids,
           lambda: Count('pk', distinct=True), unit='count'),
    Metric('sales.void_value', 'Value of voided sales', 'What the voided sales had been charged.',
           MetricGroup.SALES, 'voids', Aggregation.SUM, _voids, lambda: Sum('lines__amount')),

    # ── profit ──
    Metric('profit.cogs', 'Cost of goods sold', 'Quantity sold times the cost of the batch it came from.',
           MetricGroup.PROFIT, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum(_LINE_COST())),
    Metric('profit.gross', 'Gross profit', 'Net sales less the cost of the goods sold.',
           MetricGroup.PROFIT, 'sales', Aggregation.SUM, _sale_lines, lambda: Sum(_LINE_PROFIT())),
    Metric('profit.margin', 'Gross margin (%)', 'Gross profit as a share of net sales.',
           MetricGroup.PROFIT, 'sales', Aggregation.RATIO, _sale_lines,
           lambda: Sum(_LINE_PROFIT()), lambda: Sum('amount'), scale=100, unit='percent'),
    Metric('profit.markup', 'Markup (%)', 'Gross profit as a share of the cost of the goods sold.',
           MetricGroup.PROFIT, 'sales', Aggregation.RATIO, _sale_lines,
           lambda: Sum(_LINE_PROFIT()), lambda: Sum(_LINE_COST()), scale=100, unit='percent'),

    # ── purchases ──
    Metric('purchases.value', 'Purchases', 'Received supplier invoices: quantity times pack price.',
           MetricGroup.PURCHASES, 'purchases', Aggregation.SUM, _purchase_lines,
           lambda: Sum(_dec(F('order_qty') * F('pack_price')))),
    Metric('purchases.qty', 'Quantity received', "Units received, in each product's own stock unit.",
           MetricGroup.PURCHASES, 'purchases', Aggregation.SUM, _purchase_lines,
           lambda: Sum(_dec(F('order_qty') * F('uom__unit_value') / F('product__uom__unit_value'))), unit='qty'),
    Metric('purchases.invoices', 'Supplier invoices', 'Received supplier invoices.',
           MetricGroup.PURCHASES, 'purchases', Aggregation.COUNT_DISTINCT, _purchase_lines,
           lambda: Count('invoice', distinct=True), unit='count'),
    Metric('purchases.suppliers', 'Suppliers bought from', 'Distinct suppliers with a received invoice.',
           MetricGroup.PURCHASES, 'purchases', Aggregation.COUNT_DISTINCT, _purchase_lines,
           lambda: Count('invoice__supplier', distinct=True), unit='count'),
    Metric('purchases.paid', 'Paid to suppliers', 'Payments recorded against supplier invoices.',
           MetricGroup.PURCHASES, 'supplier_payments', Aggregation.SUM, SupplierPayment.objects.all,
           lambda: Sum('amount')),

    # ── stock ──
    Metric('stock.on_hand', 'Stock on hand (closing)', 'Units in stock at the end of the period, expired included.',
           MetricGroup.STOCK, 'stock_balance', Aggregation.BALANCE, _ledger, lambda: Sum('qty_delta'), unit='qty'),
    Metric('stock.value', 'Stock value at cost (closing)', 'Stock at the end of the period, at batch cost.',
           MetricGroup.STOCK, 'stock_balance', Aggregation.BALANCE, _ledger, lambda: Sum(_MOVE_VALUE())),
    Metric('stock.in', 'Stock in', 'Units added: received, transferred in, counted up, voids returned.',
           MetricGroup.STOCK, 'stock_moves', Aggregation.SUM, _ledger,
           lambda: Sum('qty_delta', filter=Q(qty_delta__gt=0)), unit='qty'),
    Metric('stock.out', 'Stock out', 'Units removed: sold, transferred out, written off, counted down.',
           MetricGroup.STOCK, 'stock_moves', Aggregation.SUM, _ledger,
           lambda: Sum(_dec(-F('qty_delta')), filter=Q(qty_delta__lt=0)), unit='qty'),
    Metric('stock.net_change', 'Net stock change', 'Stock in less stock out.',
           MetricGroup.STOCK, 'stock_moves', Aggregation.SUM, _ledger, lambda: Sum('qty_delta'), unit='qty'),
    Metric('stock.wastage', 'Stock lost or wasted', 'Units written off as lost, stolen, damaged, expired or spoiled.',
           MetricGroup.STOCK, 'stock_moves', Aggregation.SUM, _ledger,
           lambda: Sum(_dec(-F('qty_delta')), filter=_WASTE), unit='qty'),
    Metric('stock.wastage_value', 'Value lost or wasted', 'Write-offs at batch cost.',
           MetricGroup.STOCK, 'stock_moves', Aggregation.SUM, _ledger,
           lambda: Sum(_dec(-F('qty_delta') * F('batch__unit_cost')), filter=_WASTE)),

    # ── customer credit ──
    Metric('credit.given', 'Sold on credit', "The share of sales put on customers' accounts.",
           MetricGroup.CREDIT, 'receipts', Aggregation.SUM, _receipts, lambda: Sum('credit_amount')),
    Metric('credit.customers', 'Customers buying on credit', 'Distinct customers with a credit sale.',
           MetricGroup.CREDIT, 'receipts', Aggregation.COUNT_DISTINCT, _receipts,
           lambda: Count('customer', distinct=True, filter=Q(credit_amount__gt=0)), unit='count'),
    Metric('credit.repaid', 'Credit repaid', 'Repayments received from customers (voided ones excluded).',
           MetricGroup.CREDIT, 'credit_payments', Aggregation.SUM, _credit_payments, lambda: Sum('amount')),
    Metric('credit.repayments', 'Number of repayments', 'Repayments received from customers.',
           MetricGroup.CREDIT, 'credit_payments', Aggregation.COUNT, _credit_payments,
           lambda: Count('pk'), unit='count'),

    # ── tills ──
    Metric('tills.shifts', 'Shifts closed', 'Till shifts closed with a counted drawer.',
           MetricGroup.TILLS, 'shifts', Aggregation.COUNT, _closed_shifts, lambda: Count('pk'), unit='count'),
    Metric('tills.variance', 'Cash over / short', 'Counted cash less expected cash; negative means short.',
           MetricGroup.TILLS, 'shifts', Aggregation.SUM, _closed_shifts,
           lambda: Sum(_dec(F('counted_cash') - F('expected_cash')))),
    Metric('tills.short', 'Cash short', 'Expected cash missing from drawers that came up short.',
           MetricGroup.TILLS, 'shifts', Aggregation.SUM, _closed_shifts,
           lambda: Sum(_dec(F('expected_cash') - F('counted_cash')), filter=Q(counted_cash__lt=F('expected_cash')))),
    Metric('tills.short_shifts', 'Shifts short of cash', 'Closed shifts whose drawer was short.',
           MetricGroup.TILLS, 'shifts', Aggregation.COUNT, _closed_shifts,
           lambda: Count('pk', filter=Q(counted_cash__lt=F('expected_cash'))), unit='count'),
]
METRICS: dict[str, Metric] = {m.id: m for m in _METRICS}


# ── dimensions ─────────────────────────────────────────────────────────────

class DimensionKind:
    DATA = 'data'
    PERIOD = 'period'
    ORG_UNIT = 'org_unit'
    DYNAMIC = 'dynamic'


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    kind: str
    # Fact source id → what to group by. For `dx` and `pe` this is empty:
    # periods attach through each source's date.
    group_by: Mapping[str, FieldRef] = field(default_factory=dict)
    # ctx → [{id, label}], or None for a dimension with too many items to
    # list up front (`search` then finds them).
    items: Callable[[Context], list[dict]] | None = None
    # (ctx, text, ids) → [{id, label}] matching the text or the given ids.
    search: Callable[[Context, str, list], list[dict]] | None = None
    # ctx → how many items there are, to bound the size of a query.
    count: Callable[[Context], int] | None = None
    # Label for facts with no value (a walk-in customer, no category).
    blank_label: str = '(blank)'
    filter_only: bool = False

    @property
    def source_ids(self) -> list[str]:
        if self.kind in (DimensionKind.DATA, DimensionKind.PERIOD):
            return list(SOURCES)
        return list(self.group_by)

    @property
    def lazy(self) -> bool:
        return self.items is None and self.search is not None

    def field_for(self, source_id: str) -> FieldRef:
        return self.group_by[source_id]

    def all_items(self, ctx) -> dict[str, str]:
        return {i['id']: i['label'] for i in self.items(ctx)} if self.items else {}


def _choices(choices) -> Callable[[Context], list[dict]]:
    return lambda ctx: [{'id': str(value), 'label': str(label)} for value, label in choices]


# Paths from each source to the product, for the product dimensions.
_PRODUCT_PATHS = {
    'sales': 'batch__product',
    'purchases': 'product',
    'stock_moves': 'batch__product',
    'stock_balance': 'batch__product',
}
_BATCH_PATHS = {'sales': 'batch', 'stock_moves': 'batch', 'stock_balance': 'batch'}


def _product_paths(attr: str) -> dict[str, str]:
    return {s: f'{path}__{attr}' for s, path in _PRODUCT_PATHS.items()}


def _category_items(ctx):
    return [{'id': str(pk), 'label': name}
            for pk, name in Category.objects.filter(ctx.entity_filter('')).values_list('id', 'name')]


def _brand_items(ctx):
    brands = (Product.objects.filter(ctx.entity_filter('')).exclude(brand='')
              .order_by('brand').values_list('brand', flat=True).distinct())
    return [{'id': b, 'label': b} for b in brands]


def _supplier_items(ctx):
    return [{'id': str(pk), 'label': name}
            for pk, name in Supplier.objects.filter(ctx.entity_filter('')).values_list('id', 'name')]


def _payment_method_items(ctx):
    return [{'id': str(pk), 'label': name} for pk, name in PaymentMethod.objects.values_list('id', 'name')]


def _user_label(first, last, username):
    return ' '.join(p for p in (first, last) if p) or username


def _staff_items(ctx):
    return [{'id': str(pk), 'label': _user_label(first, last, username)}
            for pk, first, last, username in User.objects.filter(ctx.entity_filter(''))
            .order_by('first_name', 'last_name', 'username')
            .values_list('id', 'first_name', 'last_name', 'username')]


SEARCH_LIMIT = 100


def _search(model, fields, label):
    """A `search` for a long list: any of `ids` (to name a saved selection
    or a query's results), then, unless `text` is None, at most SEARCH_LIMIT
    items whose `fields` contain the text."""
    def search(ctx, text, ids):
        qs = model.objects.filter(ctx.entity_filter(''))
        found = list(qs.filter(pk__in=ids)) if ids else []
        if text is not None:
            cond = Q()
            for f in fields:
                cond |= Q(**{f'{f}__icontains': text})
            found += list(qs.filter(cond).exclude(pk__in=ids or [])[:SEARCH_LIMIT])
        return [{'id': str(o.pk), 'label': label(o)} for o in found]
    return search


def _product_label(p):
    # Many names already carry the size ("Cooking oil 1L"); don't repeat it.
    squash = lambda s: s.replace(' ', '').lower()  # noqa: E731
    if p.size and squash(p.size) not in squash(p.name):
        return f'{p.name} {p.size}'
    return p.name


def _count(model):
    return lambda ctx: model.objects.filter(ctx.entity_filter('')).count()


def _hour(path):
    return lambda: ExtractHour(path, tzinfo=timezone.get_current_timezone())


def _weekday(path):
    return lambda: ExtractIsoWeekDay(path, tzinfo=timezone.get_current_timezone())


_HOURS = lambda ctx: [{'id': str(h), 'label': f'{h:02d}:00–{(h + 1) % 24:02d}:00'} for h in range(24)]  # noqa: E731
_WEEKDAYS = lambda ctx: [  # noqa: E731
    {'id': str(i), 'label': d}
    for i, d in enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'], 1)
]


def _credit_sale(credit_path):
    return lambda: Case(
        When(**{f'{credit_path}__gt': 0}, then=Value('credit')),
        default=Value('paid'), output_field=CharField(),
    )


def _expiry(batch_path):
    """Where a batch's expiry date stands today. Evaluated per query, so
    'today' is the day the question is asked."""
    def build():
        today = timezone.localdate()
        expiry = f'{batch_path}__expiry_date'
        return Case(
            When(**{f'{expiry}__isnull': True}, then=Value('none')),
            When(**{f'{expiry}__lt': today}, then=Value('expired')),
            When(**{f'{expiry}__lte': today + datetime.timedelta(days=30)}, then=Value('soon')),
            When(**{f'{expiry}__lte': today + datetime.timedelta(days=90)}, then=Value('quarter')),
            default=Value('later'), output_field=CharField(),
        )
    return build


_EXPIRY_ITEMS = _choices([
    ('expired', 'Expired'), ('soon', 'Expires within 30 days'), ('quarter', 'Expires in 31–90 days'),
    ('later', 'Expires later'), ('none', 'Does not expire'),
])

L = StockLedger.LedgerType


def _movement():
    """The ledger entry as a shopkeeper names it: receiving and transfers
    both post Transfer In, so the reference tells them apart."""
    return Case(
        When(ledger_type=L.TRANSFER_IN, ref_type='receiving_invoice', then=Value('received')),
        When(ledger_type=L.TRANSFER_IN, then=Value('transfer_in')),
        When(ledger_type=L.TRANSFER_OUT, then=Value('transfer_out')),
        When(ledger_type=L.SOLD, then=Value('sold')),
        When(ledger_type=L.SALE_VOID, then=Value('sale_void')),
        When(ledger_type=L.OPENING_STOCK, then=Value('opening')),
        When(ledger_type=L.STOCK_COUNT, then=Value('count')),
        When(ledger_type=L.CONSUMPTION, then=Value('consumption')),
        When(ledger_type=L.WRONG_ENTRY, then=Value('correction')),
        default=Value('wastage'), output_field=CharField(),
    )


_MOVEMENT_ITEMS = _choices([
    ('received', 'Received from suppliers'), ('transfer_in', 'Transferred in'),
    ('transfer_out', 'Transferred out'), ('sold', 'Sold'), ('sale_void', 'Returned by a voided sale'),
    ('opening', 'Opening stock'), ('count', 'Stock count correction'), ('consumption', 'Internal use'),
    ('correction', 'Wrong entry corrected'), ('wastage', 'Lost, damaged, expired or spoiled'),
])

_STORE_PATHS = {s.id: f'{s.store}_id' for s in _SOURCES}

_DIMENSIONS = [
    Dimension('dx', 'Data', DimensionKind.DATA),
    Dimension('pe', 'Period', DimensionKind.PERIOD),
    Dimension('ou', 'Stores', DimensionKind.ORG_UNIT, group_by=_STORE_PATHS),

    # products
    Dimension('product', 'Product', DimensionKind.DYNAMIC, group_by=_product_paths('id'),
              search=_search(Product, ('name', 'short_name', 'brand', 'barcode'), _product_label),
              count=_count(Product)),
    Dimension('category', 'Category', DimensionKind.DYNAMIC, group_by=_product_paths('category_id'),
              items=_category_items, blank_label='No category'),
    Dimension('brand', 'Brand', DimensionKind.DYNAMIC, group_by=_product_paths('brand'),
              items=_brand_items, blank_label='No brand'),
    Dimension('vat_class', 'VAT class', DimensionKind.DYNAMIC,
              group_by={**_product_paths('vat_class'), 'sales': 'vat_class'},
              items=_choices(Product.VatClass.choices)),
    Dimension('expiry', 'Expiry (as of today)', DimensionKind.DYNAMIC,
              group_by={s: _expiry(path) for s, path in _BATCH_PATHS.items()}, items=_EXPIRY_ITEMS),

    # selling
    Dimension('payment_method', 'Payment method', DimensionKind.DYNAMIC,
              group_by={'sales': 'sale__payment_method_id', 'receipts': 'payment_method_id',
                        'voids': 'payment_method_id', 'credit_payments': 'payment_method_id'},
              items=_payment_method_items),
    Dimension('credit_sale', 'Paid or on credit', DimensionKind.DYNAMIC,
              group_by={'sales': _credit_sale('sale__credit_amount'), 'receipts': _credit_sale('credit_amount')},
              items=_choices([('paid', 'Paid in full'), ('credit', 'Part or all on credit')])),
    Dimension('cashier', 'Cashier', DimensionKind.DYNAMIC,
              group_by={'sales': 'sale__cashier_id', 'receipts': 'cashier_id', 'voids': 'cashier_id',
                        'credit_payments': 'received_by_id', 'shifts': 'cashier_id'},
              items=_staff_items),
    Dimension('customer', 'Customer', DimensionKind.DYNAMIC,
              group_by={'sales': 'sale__customer_id', 'receipts': 'customer_id', 'credit_payments': 'customer_id'},
              search=_search(Customer, ('name', 'phone'), lambda c: c.name), count=_count(Customer),
              blank_label='Walk-in (not registered)'),
    Dimension('hour', 'Hour of day', DimensionKind.DYNAMIC,
              group_by={'sales': _hour('sale__completed_at'), 'receipts': _hour('completed_at')},
              items=_HOURS),
    Dimension('weekday', 'Day of week', DimensionKind.DYNAMIC,
              group_by={'sales': _weekday('sale__completed_at'), 'receipts': _weekday('completed_at'),
                        'purchases': _weekday('invoice__received_date')},
              items=_WEEKDAYS),

    # buying
    Dimension('supplier', 'Supplier', DimensionKind.DYNAMIC,
              group_by={'purchases': 'invoice__supplier_id', 'supplier_payments': 'invoice__supplier_id'},
              items=_supplier_items),
    Dimension('supplier_payment_method', 'Supplier payment method', DimensionKind.DYNAMIC,
              group_by={'supplier_payments': 'method'}, items=_choices(SupplierPayment.Method.choices)),

    # stock
    Dimension('movement', 'Stock movement', DimensionKind.DYNAMIC,
              group_by={'stock_moves': _movement}, items=_MOVEMENT_ITEMS),
    Dimension('ledger_type', 'Ledger entry type', DimensionKind.DYNAMIC,
              group_by={'stock_moves': 'ledger_type'}, items=_choices(L.choices)),
]
DIMENSIONS: dict[str, Dimension] = {d.id: d for d in _DIMENSIONS}


# ── org units ──────────────────────────────────────────────────────────────

FIRM = 'FIRM'


def firm_label(ctx: Context) -> str:
    if ctx.store_ids is not None:
        return 'All my stores'
    return ctx.entity.name if ctx.entity is not None else 'All stores'


def org_units(ctx: Context) -> dict[str, dict]:
    """Every org-unit id the caller may name → its level and label."""
    units = {FIRM: {'level': 'firm', 'label': firm_label(ctx)}}
    for pk, name, active in ctx.stores().values_list('id', 'name', 'is_active'):
        units[str(pk)] = {'level': 'store', 'label': name if active else f'{name} (closed)'}
    return units


def _org_unit_tree(ctx: Context) -> list[dict]:
    units = org_units(ctx)
    return [{
        'id': FIRM, 'label': units[FIRM]['label'], 'level': 'firm',
        'children': [{'id': i, 'label': u['label'], 'level': 'store'}
                     for i, u in units.items() if i != FIRM],
    }]


# ── what a caller can see ──────────────────────────────────────────────────

def visible_metrics(ctx: Context) -> list[Metric]:
    return [m for m in _METRICS if group_enabled(m.group, ctx)]


def visible_dimensions(ctx: Context) -> list[tuple[Dimension, list[str]]]:
    """(dimension, the visible source ids it applies to) for every dimension
    that applies to at least one visible metric's source."""
    source_ids = {m.source for m in visible_metrics(ctx)}
    out = []
    for dim in _DIMENSIONS:
        applies = [s for s in dim.source_ids if s in source_ids]
        if applies:
            out.append((dim, applies))
    return out


def _metric_items(metrics) -> list[dict]:
    return [
        {'id': m.id, 'label': m.label, 'description': m.description, 'group': m.group,
         'source': m.source, 'aggregation': m.aggregation, 'unit': m.unit}
        for m in metrics
    ]


def catalogue(ctx: Context) -> dict:
    """The registry as the frontend sees it: feature- and store-filtered,
    with no ORM paths."""
    metrics = visible_metrics(ctx)
    used = {m.source for m in metrics}
    dimensions = []
    for dim, applies in visible_dimensions(ctx):
        entry = {
            'id': dim.id, 'label': dim.label, 'kind': dim.kind, 'applies_to': applies,
            'filter_only': dim.filter_only, 'lazy': dim.lazy, 'blank_label': dim.blank_label,
        }
        if dim.kind == DimensionKind.DATA:
            entry['items'] = _metric_items(metrics)
        elif dim.kind == DimensionKind.PERIOD:
            entry['items'] = [{'id': code, 'label': label, 'type': 'relative', 'period_type': ptype}
                              for code, label, ptype in RELATIVE_PERIODS]
            entry['period_types'] = [{'id': t, 'label': label} for t, label in PERIOD_TYPES]
        elif dim.kind == DimensionKind.ORG_UNIT:
            entry['items'] = _org_unit_tree(ctx)
        else:
            entry['items'] = dim.items(ctx) if dim.items else []
        dimensions.append(entry)
    groups = list(dict.fromkeys(m.group for m in metrics))
    return {
        'groups': [{'id': g, 'label': GROUP_LABELS[g]} for g in groups],
        'sources': [{'id': s.id, 'label': s.label, 'grain': s.grain, 'cumulative': s.cumulative}
                    for s in _SOURCES if s.id in used],
        'dimensions': dimensions,
    }


# ── saved visualizations ───────────────────────────────────────────────────

class Unavailable:
    FEATURE_DISABLED = 'feature_disabled'
    UNKNOWN = 'unknown'


_FIXED_DIMENSIONS = ('dx', 'pe', 'ou')


def unavailable_references(config, ctx: Context) -> list[dict]:
    """The metrics and dimensions a saved visualization config uses that the
    caller can't query: a feature is switched off, or the registry no longer
    has it. Labels come from the full registry, so the viewer can be told
    what is missing even when their catalogue omits it."""
    config = config if isinstance(config, dict) else {}
    items = config.get('items') if isinstance(config.get('items'), dict) else {}
    out = []

    def missing(kind, ref_id, label, reason, features=()):
        out.append({'kind': kind, 'id': ref_id, 'label': label, 'reason': reason,
                    'features': [FEATURE_LABELS[f] for f in features if not ctx.feature_on(f)]})

    metric_ids = items.get('dx') if isinstance(items.get('dx'), list) else []
    for metric_id in metric_ids:
        metric = METRICS.get(metric_id)
        if metric is None:
            missing('metric', str(metric_id), str(metric_id), Unavailable.UNKNOWN)
        elif not group_enabled(metric.group, ctx):
            missing('metric', metric.id, metric.label, Unavailable.FEATURE_DISABLED, GROUP_FEATURES[metric.group])

    visible = {dim.id for dim, _ in visible_dimensions(ctx)}
    placed = []
    for axis in ('columns', 'rows', 'filters'):
        ids = config.get(axis) if isinstance(config.get(axis), list) else []
        placed += [d for d in ids if d not in placed and d not in _FIXED_DIMENSIONS]
    for dim_id in placed:
        dim = DIMENSIONS.get(dim_id)
        if dim is None:
            missing('dimension', str(dim_id), str(dim_id), Unavailable.UNKNOWN)
        elif dim.id not in visible:
            features = dict.fromkeys(
                f for m in _METRICS if m.source in dim.source_ids for f in GROUP_FEATURES[m.group])
            missing('dimension', dim.id, dim.label, Unavailable.FEATURE_DISABLED, features)
    return out
