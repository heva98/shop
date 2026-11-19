"""Building blocks shared by every report module (views, summary, finance)
and by the end-of-day SMS/email (notifications): which stores and dates a
request covers, sale totals computed in the database, and stock on hand.

Kept apart from the endpoints so other apps import a service, not a views
module, and the report modules don't import each other's private names.
"""

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Case, Count, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.exceptions import PermissionDenied, ValidationError

from catalog.models import Product
from core.models import Role, Store, StoreRole
from core.money import CENT, ZERO, money, vat_portion
from core.queryset_scoping import accessible_store_ids
from inventory.models import StockBatch, StoreProduct
from pos.models import Sale, Shift
from receiving.models import ReceivingInvoice

MANAGEMENT_ROLES = (Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)
MONEY_FIELD = DecimalField(max_digits=16, decimal_places=2)
QTY_FIELD = DecimalField(max_digits=16, decimal_places=2)
COST_FIELD = DecimalField(max_digits=20, decimal_places=4)


def _gate_roles(request):
    """The roles the endpoint's role gate (core.permissions.roles) allows,
    or None for an endpoint open to every role."""
    view = (getattr(request, 'parser_context', None) or {}).get('view')
    for permission in getattr(view, 'permission_classes', ()):
        allowed = getattr(permission, 'allowed_roles', None)
        if allowed:
            return allowed
    return None


def stores_for(request):
    """The stores a report covers: ?store=<id> if the caller may see it,
    else every store they can see. For a report limited to some roles
    (stock value, margins...), only the stores where the caller holds one
    of them: a storekeeper at one branch who is a cashier at another sees
    the first branch's figures, not both."""
    user = request.user
    qs = Store.objects.all() if user.is_superuser else Store.objects.filter(entity_id=user.entity_id)
    ids = accessible_store_ids(user)
    if ids is not None:
        allowed = _gate_roles(request)
        if allowed is not None:
            ids = StoreRole.objects.filter(user=user, role__in=allowed, store_id__in=ids).values_list('store_id', flat=True)
        qs = qs.filter(id__in=list(ids))
    store_id = request.query_params.get('store')
    if store_id:
        try:
            uuid.UUID(store_id)
        except ValueError:
            raise ValidationError({'store': gettext('Not a valid store id.')})
        qs = qs.filter(id=store_id)
        if not qs.exists():
            raise PermissionDenied(gettext('You do not have access to this store.'))
    return qs


def date_range(request):
    """(start, end) from ?start= and ?end= (YYYY-MM-DD, inclusive), each
    defaulting to today in the shop's time zone."""
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.query_params.get('start') or today.isoformat())
        end = date.fromisoformat(request.query_params.get('end') or today.isoformat())
    except ValueError:
        raise ValidationError(gettext('Dates must be YYYY-MM-DD.'))
    if end < start:
        raise ValidationError(gettext('End date is before start date.'))
    return start, end


def day_start(day):
    """The moment `day` begins in the shop's time zone."""
    return datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone())


def on_days(field, start, end=None):
    """`field` (a date and time) falls on `start`..`end` (inclusive; end
    defaults to start) in the shop's time zone. Same rows as
    field__date__gte/__lte, but as a plain range on the column, which its
    index can answer: field__date wraps every row's value in a time zone
    conversion first, so the database has to read them all."""
    return Q(**{f'{field}__gte': day_start(start), f'{field}__lt': day_start((end or start) + timedelta(days=1))})


def is_cashier_only(user, stores):
    """A cashier sees only their own shifts and their own sales history;
    everyone above them sees the whole store's."""
    if user.is_superuser:
        return False
    return not StoreRole.objects.filter(
        Q(store__in=stores) | Q(store__isnull=True), user=user, role__in=MANAGEMENT_ROLES,
    ).exists()


def sale_totals(qs):
    """Sales annotated with sale_total, sale_discount and standard_total
    (the VAT-able part), summed in the database."""
    standard_value = Case(
        When(lines__vat_class=Product.VatClass.STANDARD, then=F('lines__amount')),
        default=Value(0), output_field=MONEY_FIELD,
    )
    return qs.annotate(
        sale_total=Sum('lines__amount', output_field=MONEY_FIELD),
        sale_discount=Sum('lines__discount', output_field=MONEY_FIELD),
        standard_total=Sum(standard_value),
    )


def vat(standard_total):
    return money(vat_portion(standard_total or ZERO))


def usable_stock(stores, today):
    """{(store_id, product_id): [usable_qty, expired_qty, cost_value]} —
    expired batches still on the shelf can't be sold, so they don't count
    towards what's available."""
    # Summed in the database, one row per store and product rather than one
    # per batch. Quantities keep the column's 2 places and cost value the 4
    # of qty x unit cost, so the numbers match summing the batches by hand;
    # a sum of nothing comes back as ZERO, as it did then.
    expired = Q(expiry_date__isnull=False, expiry_date__lt=today)
    rows = (StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0)
            .values('store_id', 'product_id')
            .annotate(
                usable=Sum(Case(When(expired, then=Value(0)), default=F('qty_on_hand'), output_field=QTY_FIELD)),
                expired=Sum(Case(When(expired, then=F('qty_on_hand')), default=Value(0), output_field=QTY_FIELD)),
                cost=Sum(F('qty_on_hand') * F('unit_cost'), output_field=COST_FIELD),
            ).order_by())
    out = defaultdict(lambda: [ZERO, ZERO, ZERO])
    for row in rows:
        out[(row['store_id'], row['product_id'])] = [
            _places(row['usable'], CENT), _places(row['expired'], CENT), _places(row['cost'], _COST_PLACES)]
    return out


_COST_PLACES = Decimal('0.0001')


def stock_status_counts(stores, today):
    """{'out', 'low', 'at_or_below_reorder'}: how many of the products the
    stores stock (StoreProduct, enabled) have no usable stock, have some
    but no more than the reorder level, and either. Counted in the
    database rather than by loading every product's level."""
    usable = (StockBatch.objects.filter(store=OuterRef('store_id'), product=OuterRef('product_id'), qty_on_hand__gt=0)
              .filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today))
              .values('store', 'product').annotate(t=Sum('qty_on_hand')).values('t'))
    return (StoreProduct.objects.filter(store__in=stores, enabled=True)
            .annotate(usable=Coalesce(Subquery(usable), Value(ZERO), output_field=QTY_FIELD))
            .aggregate(out=Count('pk', filter=Q(usable__lte=0)),
                       low=Count('pk', filter=Q(usable__gt=0, usable__lte=F('reorder_level'))),
                       at_or_below_reorder=Count('pk', filter=Q(usable__lte=F('reorder_level')))))


def _places(value, exponent):
    """A database sum with the exact places the column's own arithmetic
    gives (SQLite returns sums unrounded, e.g. 4.5 or 841.095000000000);
    ZERO for nothing."""
    return Decimal(value).quantize(exponent) if value else ZERO


def summarize_day(store, day):
    """One store's day in numbers, for the end-of-day SMS/email
    (notifications.management.commands.send_daily_summaries)."""
    sales = list(sale_totals(Sale.objects.filter(on_days('completed_at', day), store=store, status=Sale.Status.COMPLETED)
                             .select_related('payment_method')))
    by_method = {}
    for s in sales:
        for name, _impl, amount in s.payment_split(s.sale_total or ZERO):
            by_method[name] = by_method.get(name, ZERO) + amount
    low = stock_status_counts(Store.objects.filter(pk=store.pk), day)['at_or_below_reorder']
    variance = sum((sh.counted_cash - sh.expected_cash
                    for sh in Shift.objects.filter(on_days('closed_at', day), store=store, counted_cash__isnull=False)), ZERO)
    purchases = ReceivingInvoice.objects.filter(
        store=store, status=ReceivingInvoice.Status.RECEIVED, received_date=day,
    ).aggregate(total=Sum(F('lines__order_qty') * F('lines__pack_price'), output_field=MONEY_FIELD))['total']
    return {
        'sales_count': len(sales),
        'sales_total': sum((by_method.values()), ZERO),
        'by_method': sorted(by_method.items()),
        'void_count': Sale.objects.filter(on_days('voided_at', day), store=store, status=Sale.Status.VOIDED).count(),
        'missing_efd': sum(1 for s in sales if s.efd_receipt_no == ''),
        'variance': variance,
        'purchases_total': purchases or ZERO,
        'low_stock': low,
        'expiring': StockBatch.objects.filter(
            store=store, qty_on_hand__gt=0, expiry_date__gte=day, expiry_date__lte=day + timedelta(days=30)).count(),
    }
