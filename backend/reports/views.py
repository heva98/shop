"""Read-only report endpoints computed live from the transactional tables.

Every endpoint takes an optional ?store=<id>; without it, the report
covers every store the caller can see (one store for store staff, the
whole firm for an entity_admin). Date ranges are ?start=YYYY-MM-DD and
?end=YYYY-MM-DD, inclusive, in the shop's local time zone, defaulting
to today.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Product
from core.models import Role, Store, StoreRole
from core.permissions import roles
from core.queryset_scoping import accessible_store_ids
from enquiry.models import Enquiry
from inventory.models import StockAdjustment, StockBatch, StockLedger, StoreProduct
from pos.models import VAT_RATE, Sale, SaleLine, Shift
from pricing.models import Price
from receiving.models import ReceivingInvoice

_MANAGEMENT_ROLES = (Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)
_ZERO = Decimal('0')
_MONEY = DecimalField(max_digits=16, decimal_places=2)


def _money(value):
    return Decimal(value or 0).quantize(Decimal('0.01'))


def _stores(request):
    user = request.user
    qs = Store.objects.all() if user.is_superuser else Store.objects.filter(entity_id=user.entity_id)
    ids = accessible_store_ids(user)
    if ids is not None:
        qs = qs.filter(id__in=list(ids))
    store_id = request.query_params.get('store')
    if store_id:
        try:
            uuid.UUID(store_id)
        except ValueError:
            raise ValidationError({'store': 'Not a valid store id.'})
        qs = qs.filter(id=store_id)
        if not qs.exists():
            raise PermissionDenied('You do not have access to this store.')
    return qs


def _date_range(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.query_params.get('start') or today.isoformat())
        end = date.fromisoformat(request.query_params.get('end') or today.isoformat())
    except ValueError:
        raise ValidationError('Dates must be YYYY-MM-DD.')
    if end < start:
        raise ValidationError('End date is before start date.')
    return start, end


def _is_cashier_only(user, stores):
    """A cashier sees only their own shifts and their own sales history;
    everyone above them sees the whole store's."""
    if user.is_superuser:
        return False
    return not StoreRole.objects.filter(
        Q(store__in=stores) | Q(store__isnull=True), user=user, role__in=_MANAGEMENT_ROLES,
    ).exists()


def _sale_totals(qs):
    standard_value = Case(
        When(lines__vat_class=Product.VatClass.STANDARD, then=F('lines__amount')),
        default=Value(0), output_field=_MONEY,
    )
    return qs.annotate(
        sale_total=Sum('lines__amount', output_field=_MONEY),
        sale_discount=Sum('lines__discount', output_field=_MONEY),
        standard_total=Sum(standard_value),
    )


def _vat(standard_total):
    return _money((standard_total or _ZERO) * VAT_RATE / (1 + VAT_RATE))


def _usable_stock(stores, today):
    """{(store_id, product_id): (usable_qty, expired_qty, cost_value)} —
    expired batches still on the shelf can't be sold, so they don't count
    towards what's available."""
    out = defaultdict(lambda: [_ZERO, _ZERO, _ZERO])
    for b in StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0):
        row = out[(b.store_id, b.product_id)]
        if b.expiry_date is not None and b.expiry_date < today:
            row[1] += b.qty_on_hand
        else:
            row[0] += b.qty_on_hand
        row[2] += b.qty_on_hand * b.unit_cost
    return out


def summarize_day(store, day):
    """One store's day in numbers, for the end-of-day SMS/email
    (notifications.management.commands.send_daily_summaries)."""
    sales = _sale_totals(Sale.objects.filter(store=store, status=Sale.Status.COMPLETED, completed_at__date=day)
                         .select_related('payment_method'))
    by_method = {}
    for s in sales:
        for name, _impl, amount in s.payment_split(s.sale_total or _ZERO):
            by_method[name] = by_method.get(name, _ZERO) + amount
    stock = _usable_stock(Store.objects.filter(pk=store.pk), day)
    low = sum(
        1 for sp in StoreProduct.objects.filter(store=store, enabled=True)
        if stock.get((store.id, sp.product_id), [_ZERO])[0] <= sp.reorder_level
    )
    variance = sum((Decimal(sh.counted_cash) - Decimal(sh.expected_cash)
                    for sh in Shift.objects.filter(store=store, closed_at__date=day, counted_cash__isnull=False)), _ZERO)
    purchases = ReceivingInvoice.objects.filter(
        store=store, status=ReceivingInvoice.Status.RECEIVED, received_date=day,
    ).aggregate(total=Sum(F('lines__order_qty') * F('lines__pack_price'), output_field=_MONEY))['total']
    return {
        'sales_count': sales.count(),
        'sales_total': sum((by_method.values()), _ZERO),
        'by_method': sorted(by_method.items()),
        'void_count': Sale.objects.filter(store=store, status=Sale.Status.VOIDED, voided_at__date=day).count(),
        'missing_efd': sales.filter(efd_receipt_no='').count(),
        'variance': variance,
        'purchases_total': purchases or _ZERO,
        'low_stock': low,
        'expiring': StockBatch.objects.filter(
            store=store, qty_on_hand__gt=0, expiry_date__gte=day, expiry_date__lte=day + timedelta(days=30)).count(),
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard(request):
    stores = _stores(request)
    today = timezone.localdate()

    sales_today = _sale_totals(Sale.objects.filter(
        store__in=stores, status=Sale.Status.COMPLETED, completed_at__date=today,
    ))
    sales_total = sum((s.sale_total or _ZERO for s in sales_today), _ZERO)
    missing_efd = sales_today.filter(efd_receipt_no='').count()

    stock = _usable_stock(stores, today)
    low, out = 0, 0
    for sp in StoreProduct.objects.filter(store__in=stores, enabled=True):
        qty = stock.get((sp.store_id, sp.product_id), [_ZERO])[0]
        if qty <= 0:
            out += 1
        elif qty <= sp.reorder_level:
            low += 1

    batches = StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0)
    return Response({
        'date': today,
        'store_count': stores.count(),
        'sales_today_total': _money(sales_total),
        'sales_today_count': sales_today.count(),
        'sales_missing_efd': missing_efd,
        'low_stock_count': low,
        'stocked_out_count': out,
        'expiring_30_count': batches.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30)).count(),
        'expired_on_shelf_count': batches.filter(expiry_date__lt=today).count(),
        'open_enquiries_count': Enquiry.objects.filter(
            requesting_store__in=stores, status=Enquiry.Status.OPEN,
        ).count(),
        'open_shifts_count': Shift.objects.filter(store__in=stores, closed_at__isnull=True).count(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales(request):
    stores = _stores(request)
    start, end = _date_range(request)
    qs = Sale.objects.filter(
        store__in=stores, status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED],
        completed_at__date__gte=start, completed_at__date__lte=end,
    )
    if _is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    qs = _sale_totals(qs.select_related('store', 'cashier', 'payment_method', 'customer')).order_by('completed_at')

    rows, by_method = [], {}
    gross, vat, void_total, void_count, missing_efd = _ZERO, _ZERO, _ZERO, 0, 0
    discounts, on_credit = _ZERO, _ZERO
    for s in qs:
        total = _money(s.sale_total)
        row_vat = _vat(s.standard_total)
        rows.append({
            'id': s.id, 'number': s.number, 'completed_at': s.completed_at, 'store': s.store.name,
            'cashier': (s.cashier.get_full_name() or s.cashier.username) if s.cashier else '',
            'payment_method': s.payment_method.name if s.payment_method else '',
            'payment_reference': s.payment_reference, 'efd_receipt_no': s.efd_receipt_no,
            'customer_name': s.customer_name, 'status': s.status, 'void_reason': s.void_reason,
            'total': total, 'vat': row_vat, 'discount': _money(s.sale_discount or _ZERO),
            'credit': _money(s.credit_amount),
        })
        if s.status == Sale.Status.VOIDED:
            void_count += 1
            void_total += total
            continue
        gross += total
        vat += row_vat
        discounts += s.sale_discount or _ZERO
        on_credit += s.credit_amount
        if not s.efd_receipt_no:
            missing_efd += 1
        for name, _impl, amount in s.payment_split(total):
            method = by_method.setdefault(name, {'payment_method': name, 'count': 0, 'total': _ZERO})
            method['count'] += 1
            method['total'] += amount

    line_qs = SaleLine.objects.filter(sale__in=[r['id'] for r in rows if r['status'] == Sale.Status.COMPLETED])
    by_product = (
        line_qs.values('batch__product_id', 'batch__product__name', 'batch__product__uom__name')
        .annotate(qty_total=Sum('qty'), value=Sum('amount', output_field=_MONEY))
        .order_by('-value')
    )
    return Response({
        'start': start, 'end': end,
        'summary': {
            'sales_count': len(rows) - void_count, 'gross_total': _money(gross), 'vat_total': _money(vat),
            'void_count': void_count, 'void_total': _money(void_total), 'missing_efd_count': missing_efd,
            'discount_total': _money(discounts), 'credit_total': _money(on_credit),
            'by_payment_method': [{**m, 'total': _money(m['total'])} for m in by_method.values()],
        },
        'sales': rows,
        'by_product': [
            {'product': r['batch__product__name'], 'unit': r['batch__product__uom__name'], 'qty': r['qty_total'], 'value': _money(r['value'])} for r in by_product
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_trend(request):
    stores = _stores(request)
    try:
        days = min(max(int(request.query_params.get('days', 30)), 1), 366)
    except ValueError:
        raise ValidationError({'days': 'Must be a number.'})
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)
    rows = (
        SaleLine.objects.filter(
            sale__store__in=stores, sale__status=Sale.Status.COMPLETED,
            sale__completed_at__date__gte=start, sale__completed_at__date__lte=end,
        )
        .annotate(day=TruncDate('sale__completed_at'))
        .values('day').annotate(total=Sum('amount', output_field=_MONEY))
    )
    by_day = {r['day']: r['total'] for r in rows}
    return Response([
        {'date': start + timedelta(days=i), 'total': _money(by_day.get(start + timedelta(days=i)))}
        for i in range(days)
    ])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shifts(request):
    stores = _stores(request)
    start, end = _date_range(request)
    qs = Shift.objects.filter(
        store__in=stores, opened_at__date__gte=start, opened_at__date__lte=end,
    ).select_related('store', 'cashier').order_by('opened_at')
    if _is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    return Response({
        'start': start, 'end': end,
        'shifts': [
            {
                'id': s.id, 'store': s.store.name, 'cashier': s.cashier.get_full_name() or s.cashier.username,
                'opened_at': s.opened_at, 'closed_at': s.closed_at, 'closing_note': s.closing_note,
                **s.summary(),
            }
            for s in qs
        ],
    })


@api_view(['GET'])
@permission_classes([roles(*_MANAGEMENT_ROLES)])
def stock(request):
    stores = _stores(request)
    today = timezone.localdate()
    levels = _usable_stock(stores, today)
    reorder = {(sp.store_id, sp.product_id): sp.reorder_level for sp in StoreProduct.objects.filter(store__in=stores)}
    keys = set(levels) | set(reorder)
    products = Product.objects.in_bulk({k[1] for k in keys})
    store_names = dict(stores.values_list('id', 'name'))
    prices = {}
    for p in Price.objects.filter(product_id__in=products.keys(), entity_id__in=stores.values('entity_id'), uom__isnull=True):
        prices[(p.store_id, p.product_id)] = p.unit_price

    rows = []
    for store_id, product_id in keys:
        usable, expired, cost_value = levels.get((store_id, product_id), (_ZERO, _ZERO, _ZERO))
        level = reorder.get((store_id, product_id), _ZERO)
        price = prices.get((store_id, product_id), prices.get((None, product_id)))
        status = 'out' if usable <= 0 else ('low' if usable <= level else 'ok')
        rows.append({
            'store': store_names[store_id], 'product': products[product_id].name,
            'usable_qty': usable, 'expired_qty': expired, 'reorder_level': level, 'status': status,
            'cost_value': _money(cost_value),
            'retail_value': None if price is None else _money(usable * price),
        })
    rows.sort(key=lambda r: (r['store'], r['product']))
    return Response({
        'date': today,
        'summary': {
            'product_count': len(rows),
            'low_count': sum(1 for r in rows if r['status'] == 'low'),
            'out_count': sum(1 for r in rows if r['status'] == 'out'),
            'cost_value': _money(sum((r['cost_value'] for r in rows), _ZERO)),
            'retail_value': _money(sum((r['retail_value'] or _ZERO for r in rows), _ZERO)),
        },
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def expiry(request):
    stores = _stores(request)
    today = timezone.localdate()
    try:
        days = min(max(int(request.query_params.get('days', 90)), 0), 730)
    except ValueError:
        raise ValidationError({'days': 'Must be a number.'})
    batches = (
        StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0, expiry_date__lte=today + timedelta(days=days))
        .select_related('store', 'product').order_by('expiry_date')
    )
    rows = [
        {
            'store': b.store.name, 'product': b.product.name, 'batch_no': b.batch_no, 'expiry_date': b.expiry_date,
            'days_left': (b.expiry_date - today).days, 'qty': b.qty_on_hand,
            'cost_value': _money(b.qty_on_hand * b.unit_cost),
        }
        for b in batches
    ]
    return Response({
        'date': today, 'days': days,
        'summary': {
            'expired_count': sum(1 for r in rows if r['days_left'] < 0),
            'expiring_count': sum(1 for r in rows if r['days_left'] >= 0),
            'cost_value': _money(sum((r['cost_value'] for r in rows), _ZERO)),
        },
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([roles(*_MANAGEMENT_ROLES)])
def purchases(request):
    stores = _stores(request)
    start, end = _date_range(request)
    invoices = (
        ReceivingInvoice.objects.filter(
            store__in=stores, status=ReceivingInvoice.Status.RECEIVED,
            received_date__gte=start, received_date__lte=end,
        )
        .select_related('store', 'supplier')
        .annotate(total=Sum(F('lines__order_qty') * F('lines__pack_price'), output_field=_MONEY))
        .order_by('received_date')
    )
    rows, by_supplier = [], {}
    for inv in invoices:
        total = _money(inv.total)
        rows.append({
            'store': inv.store.name, 'supplier': inv.supplier.name, 'invoice_number': inv.invoice_number,
            'received_date': inv.received_date, 'total': total,
        })
        sup = by_supplier.setdefault(inv.supplier.name, {'supplier': inv.supplier.name, 'count': 0, 'total': _ZERO})
        sup['count'] += 1
        sup['total'] += total
    return Response({
        'start': start, 'end': end,
        'summary': {
            'invoice_count': len(rows),
            'total': _money(sum((r['total'] for r in rows), _ZERO)),
            'by_supplier': [{**s, 'total': _money(s['total'])} for s in by_supplier.values()],
        },
        'rows': rows,
    })


_LOSS_TYPES = [
    StockLedger.LedgerType.EXPIRED, StockLedger.LedgerType.DAMAGED, StockLedger.LedgerType.LOST,
    StockLedger.LedgerType.STOLEN, StockLedger.LedgerType.COLD_CHAIN_FAILURE, StockLedger.LedgerType.CONSUMPTION,
    StockLedger.LedgerType.DISPOSE, StockLedger.LedgerType.DISCARD, StockLedger.LedgerType.WRONG_ENTRY,
    StockLedger.LedgerType.STOCK_COUNT,
]


@api_view(['GET'])
@permission_classes([roles(*_MANAGEMENT_ROLES)])
def losses(request):
    """Every stock movement that isn't a sale, purchase or transfer —
    write-offs and stock-count corrections — valued at cost."""
    stores = _stores(request)
    start, end = _date_range(request)
    entries = (
        StockLedger.objects.filter(
            store__in=stores, ledger_type__in=_LOSS_TYPES,
            created_at__date__gte=start, created_at__date__lte=end,
        )
        .select_related('store', 'batch__product__uom')
        .order_by('created_at')
    )
    adjustments = {str(a.id): a for a in StockAdjustment.objects.filter(
        ledger_entry__in=entries).select_related('created_by')}
    labels = dict(StockLedger.LedgerType.choices)
    rows, by_reason = [], {}
    for e in entries:
        value = _money(e.qty_delta * e.batch.unit_cost)
        adj = adjustments.get(e.ref_id) if e.ref_type == 'stock_adjustment' else None
        rows.append({
            'date': e.created_at, 'store': e.store.name, 'product': e.batch.product.name,
            'batch_no': e.batch.batch_no, 'reason': labels.get(e.ledger_type, e.ledger_type),
            'qty': e.qty_delta, 'unit': e.batch.product.uom.name, 'value': value,
            'note': adj.note if adj else ('Lost in transit between stores' if e.ref_type == 'transfer' else ''),
            'by': (adj.created_by.get_full_name() or adj.created_by.username) if adj else '',
        })
        reason = by_reason.setdefault(e.ledger_type, {'reason': labels.get(e.ledger_type), 'count': 0, 'value': _ZERO})
        reason['count'] += 1
        reason['value'] += value
    return Response({
        'start': start, 'end': end,
        'summary': {
            'entries': len(rows),
            'value': _money(sum((r['value'] for r in rows), _ZERO)),
            'by_reason': [{**r, 'value': _money(r['value'])} for r in by_reason.values()],
        },
        'rows': rows,
    })
