"""Read-only report endpoints computed live from the transactional tables.

Every endpoint takes an optional ?store=<id>; without it, the report
covers every store the caller can see (one store for store staff, the
whole firm for an entity_admin). Date ranges are ?start=YYYY-MM-DD and
?end=YYYY-MM-DD, inclusive, in the shop's local time zone, defaulting
to today.
"""

from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Product
from core.models import display_name
from core.money import ZERO, money
from core.permissions import roles
from enquiry.models import Enquiry
from inventory.models import StockAdjustment, StockBatch, StockLedger, StoreProduct
from pos.models import Sale, SaleLine, Shift
from pricing.models import Price
from receiving.models import ReceivingInvoice

from .queries import (
    MANAGEMENT_ROLES, MONEY_FIELD, date_range, is_cashier_only, sale_totals, stores_for, usable_stock, vat,
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard(request):
    stores = stores_for(request)
    today = timezone.localdate()

    sales_today = list(sale_totals(Sale.objects.filter(
        store__in=stores, status=Sale.Status.COMPLETED, completed_at__date=today,
    )))
    sales_total = sum((s.sale_total or ZERO for s in sales_today), ZERO)
    missing_efd = sum(1 for s in sales_today if s.efd_receipt_no == '')

    stock = usable_stock(stores, today)
    low, out = 0, 0
    for sp in StoreProduct.objects.filter(store__in=stores, enabled=True):
        qty = stock.get((sp.store_id, sp.product_id), [ZERO])[0]
        if qty <= 0:
            out += 1
        elif qty <= sp.reorder_level:
            low += 1

    batches = StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0)
    return Response({
        'date': today,
        'store_count': stores.count(),
        'sales_today_total': money(sales_total),
        'sales_today_count': len(sales_today),
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
    stores = stores_for(request)
    start, end = date_range(request)
    qs = Sale.objects.filter(
        store__in=stores, status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED],
        completed_at__date__gte=start, completed_at__date__lte=end,
    )
    if is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    # Lines are aggregated from a subquery of the same sales, not a list of
    # their ids: a long date range would otherwise send thousands of ids
    # back to the database in one IN (...).
    completed_ids = qs.filter(status=Sale.Status.COMPLETED).values('pk')
    qs = sale_totals(qs.select_related('store', 'cashier', 'payment_method', 'customer')).order_by('completed_at')

    rows, by_method = [], {}
    gross, vat_sum, void_total, void_count, missing_efd = ZERO, ZERO, ZERO, 0, 0
    discounts, on_credit = ZERO, ZERO
    for s in qs:
        total = money(s.sale_total)
        row_vat = vat(s.standard_total)
        rows.append({
            'id': s.id, 'number': s.number, 'completed_at': s.completed_at, 'store': s.store.name,
            'cashier': display_name(s.cashier),
            'payment_method': s.payment_method.name if s.payment_method else '',
            'payment_reference': s.payment_reference, 'efd_receipt_no': s.efd_receipt_no,
            'customer_name': s.customer_name, 'status': s.status, 'void_reason': s.void_reason,
            'total': total, 'vat': row_vat, 'discount': money(s.sale_discount or ZERO),
            'credit': money(s.credit_amount),
        })
        if s.status == Sale.Status.VOIDED:
            void_count += 1
            void_total += total
            continue
        gross += total
        vat_sum += row_vat
        discounts += s.sale_discount or ZERO
        on_credit += s.credit_amount
        if not s.efd_receipt_no:
            missing_efd += 1
        for name, _impl, amount in s.payment_split(total):
            method = by_method.setdefault(name, {'payment_method': name, 'count': 0, 'total': ZERO})
            method['count'] += 1
            method['total'] += amount

    by_product = (
        SaleLine.objects.filter(sale__in=completed_ids).values('batch__product_id', 'batch__product__name', 'batch__product__uom__name')
        .annotate(qty_total=Sum('qty'), value=Sum('amount', output_field=MONEY_FIELD))
        .order_by('-value')
    )
    return Response({
        'start': start, 'end': end,
        'summary': {
            'sales_count': len(rows) - void_count, 'gross_total': money(gross), 'vat_total': money(vat_sum),
            'void_count': void_count, 'void_total': money(void_total), 'missing_efd_count': missing_efd,
            'discount_total': money(discounts), 'credit_total': money(on_credit),
            'by_payment_method': [{**m, 'total': money(m['total'])} for m in by_method.values()],
        },
        'sales': rows,
        'by_product': [
            {'product': r['batch__product__name'], 'unit': r['batch__product__uom__name'], 'qty': r['qty_total'], 'value': money(r['value'])} for r in by_product
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_trend(request):
    stores = stores_for(request)
    try:
        days = min(max(int(request.query_params.get('days', 30)), 1), 366)
    except ValueError:
        raise ValidationError({'days': gettext('Must be a number.')})
    end = timezone.localdate()
    start = end - timedelta(days=days - 1)
    rows = (
        SaleLine.objects.filter(
            sale__store__in=stores, sale__status=Sale.Status.COMPLETED,
            sale__completed_at__date__gte=start, sale__completed_at__date__lte=end,
        )
        .annotate(day=TruncDate('sale__completed_at'))
        .values('day').annotate(total=Sum('amount', output_field=MONEY_FIELD))
    )
    by_day = {r['day']: r['total'] for r in rows}
    return Response([
        {'date': start + timedelta(days=i), 'total': money(by_day.get(start + timedelta(days=i)))}
        for i in range(days)
    ])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def shifts(request):
    stores = stores_for(request)
    start, end = date_range(request)
    qs = Shift.objects.filter(
        store__in=stores, opened_at__date__gte=start, opened_at__date__lte=end,
    ).select_related('store', 'cashier').order_by('opened_at')
    if is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    # Each Z-report needs the shift's sales, their lines and its credit
    # repayments: prefetched for every shift at once, not three queries each.
    qs = Shift.with_summary_data(qs)
    return Response({
        'start': start, 'end': end,
        'shifts': [
            {
                'id': s.id, 'store': s.store.name, 'cashier': display_name(s.cashier),
                'opened_at': s.opened_at, 'closed_at': s.closed_at, 'closing_note': s.closing_note,
                **s.summary(),
            }
            for s in qs
        ],
    })


@api_view(['GET'])
@permission_classes([roles(*MANAGEMENT_ROLES)])
def stock(request):
    stores = stores_for(request)
    today = timezone.localdate()
    levels = usable_stock(stores, today)
    reorder = {(sp.store_id, sp.product_id): sp.reorder_level for sp in StoreProduct.objects.filter(store__in=stores)}
    keys = set(levels) | set(reorder)
    products = Product.objects.in_bulk({k[1] for k in keys})
    store_names = dict(stores.values_list('id', 'name'))
    prices = {}
    for p in Price.objects.filter(product_id__in=products.keys(), entity_id__in=stores.values('entity_id'), uom__isnull=True):
        prices[(p.store_id, p.product_id)] = p.unit_price

    rows = []
    for store_id, product_id in keys:
        usable, expired, cost_value = levels.get((store_id, product_id), (ZERO, ZERO, ZERO))
        level = reorder.get((store_id, product_id), ZERO)
        price = prices.get((store_id, product_id), prices.get((None, product_id)))
        status = 'out' if usable <= 0 else ('low' if usable <= level else 'ok')
        rows.append({
            'store': store_names[store_id], 'product': products[product_id].name,
            'usable_qty': usable, 'expired_qty': expired, 'reorder_level': level, 'status': status,
            'cost_value': money(cost_value),
            'retail_value': None if price is None else money(usable * price),
        })
    rows.sort(key=lambda r: (r['store'], r['product']))
    return Response({
        'date': today,
        'summary': {
            'product_count': len(rows),
            'low_count': sum(1 for r in rows if r['status'] == 'low'),
            'out_count': sum(1 for r in rows if r['status'] == 'out'),
            'cost_value': money(sum((r['cost_value'] for r in rows), ZERO)),
            'retail_value': money(sum((r['retail_value'] or ZERO for r in rows), ZERO)),
        },
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def expiry(request):
    stores = stores_for(request)
    today = timezone.localdate()
    try:
        days = min(max(int(request.query_params.get('days', 90)), 0), 730)
    except ValueError:
        raise ValidationError({'days': gettext('Must be a number.')})
    batches = (
        StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0, expiry_date__lte=today + timedelta(days=days))
        .select_related('store', 'product').order_by('expiry_date')
    )
    rows = [
        {
            'store': b.store.name, 'product': b.product.name, 'batch_no': b.batch_no, 'expiry_date': b.expiry_date,
            'days_left': (b.expiry_date - today).days, 'qty': b.qty_on_hand,
            'cost_value': money(b.qty_on_hand * b.unit_cost),
        }
        for b in batches
    ]
    return Response({
        'date': today, 'days': days,
        'summary': {
            'expired_count': sum(1 for r in rows if r['days_left'] < 0),
            'expiring_count': sum(1 for r in rows if r['days_left'] >= 0),
            'cost_value': money(sum((r['cost_value'] for r in rows), ZERO)),
        },
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([roles(*MANAGEMENT_ROLES)])
def purchases(request):
    stores = stores_for(request)
    start, end = date_range(request)
    invoices = (
        ReceivingInvoice.objects.filter(
            store__in=stores, status=ReceivingInvoice.Status.RECEIVED,
            received_date__gte=start, received_date__lte=end,
        )
        .select_related('store', 'supplier')
        .annotate(total=Sum(F('lines__order_qty') * F('lines__pack_price'), output_field=MONEY_FIELD))
        .order_by('received_date')
    )
    rows, by_supplier = [], {}
    for inv in invoices:
        total = money(inv.total)
        rows.append({
            'store': inv.store.name, 'supplier': inv.supplier.name, 'invoice_number': inv.invoice_number,
            'received_date': inv.received_date, 'total': total,
        })
        sup = by_supplier.setdefault(inv.supplier.name, {'supplier': inv.supplier.name, 'count': 0, 'total': ZERO})
        sup['count'] += 1
        sup['total'] += total
    return Response({
        'start': start, 'end': end,
        'summary': {
            'invoice_count': len(rows),
            'total': money(sum((r['total'] for r in rows), ZERO)),
            'by_supplier': [{**s, 'total': money(s['total'])} for s in by_supplier.values()],
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
@permission_classes([roles(*MANAGEMENT_ROLES)])
def losses(request):
    """Every stock movement that isn't a sale, purchase or transfer —
    write-offs and stock-count corrections — valued at cost."""
    stores = stores_for(request)
    start, end = date_range(request)
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
        value = money(e.qty_delta * e.batch.unit_cost)
        adj = adjustments.get(e.ref_id) if e.ref_type == 'stock_adjustment' else None
        rows.append({
            'date': e.created_at, 'store': e.store.name, 'product': e.batch.product.name,
            'batch_no': e.batch.batch_no, 'reason': labels.get(e.ledger_type, e.ledger_type),
            'qty': e.qty_delta, 'unit': e.batch.product.uom.name, 'value': value,
            'note': adj.note if adj else (gettext('Lost in transit between stores') if e.ref_type == 'transfer' else ''),
            'by': display_name(adj.created_by) if adj else '',
        })
        reason = by_reason.setdefault(e.ledger_type, {'reason': labels.get(e.ledger_type), 'count': 0, 'value': ZERO})
        reason['count'] += 1
        reason['value'] += value
    return Response({
        'start': start, 'end': end,
        'summary': {
            'entries': len(rows),
            'value': money(sum((r['value'] for r in rows), ZERO)),
            'by_reason': [{**r, 'value': money(r['value'])} for r in by_reason.values()],
        },
        'rows': rows,
    })
