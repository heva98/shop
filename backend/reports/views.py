"""Read-only report endpoints computed live from the transactional tables.

Every endpoint takes an optional ?store=<id>; without it, the report
covers every store the caller can see (one store for store staff, the
whole firm for an entity_admin). Date ranges are ?start=YYYY-MM-DD and
?end=YYYY-MM-DD, inclusive, in the shop's local time zone, defaulting
to today.
"""

from datetime import timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from catalog.models import Product
from core.models import display_name
from core.db_routing import on_replica
from core.money import ZERO, money
from core.permissions import roles
from enquiry.models import Enquiry
from inventory.models import StockAdjustment, StockBatch, StockLedger, StoreProduct
from pos.domain import split_payment
from pos.models import Sale, SaleLine, Shift
from pos.services import shifts as shift_service
from pricing.models import Price
from receiving.models import ReceivingInvoice

from .queries import (
    MANAGEMENT_ROLES, MONEY_FIELD, date_range, is_cashier_only, on_days, sale_totals, stock_status_counts, stores_for,
    usable_stock, vat,
)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@on_replica
def dashboard(request):
    stores = stores_for(request)
    today = timezone.localdate()

    # Every figure is counted or summed in the database: the dashboard is
    # opened often, and loading today's sales or every product's stock
    # level to count them grows with the shop.
    sales_today = Sale.objects.filter(on_days('completed_at', today), store__in=stores, status=Sale.Status.COMPLETED)
    counts = sales_today.aggregate(n=Count('pk'), missing_efd=Count('pk', filter=Q(efd_receipt_no='')))
    sales_total = SaleLine.objects.filter(sale__in=sales_today).aggregate(
        t=Sum('amount', output_field=MONEY_FIELD))['t'] or ZERO
    stock = stock_status_counts(stores, today)
    batches = StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0).aggregate(
        expiring=Count('pk', filter=Q(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))),
        expired=Count('pk', filter=Q(expiry_date__lt=today)),
    )
    return Response({
        'date': today,
        'store_count': stores.count(),
        'sales_today_total': money(sales_total),
        'sales_today_count': counts['n'],
        'sales_missing_efd': counts['missing_efd'],
        'low_stock_count': stock['low'],
        'stocked_out_count': stock['out'],
        'expiring_30_count': batches['expiring'],
        'expired_on_shelf_count': batches['expired'],
        'open_enquiries_count': Enquiry.objects.filter(
            requesting_store__in=stores, status=Enquiry.Status.OPEN,
        ).count(),
        'open_shifts_count': Shift.objects.filter(store__in=stores, closed_at__isnull=True).count(),
    })


SALES_PAGE_SIZE = 100
SALES_PAGE_MAX = 1000


def _page(request):
    """(page, page_size) from ?page= and ?page_size=."""
    try:
        page = max(int(request.query_params.get('page', 1)), 1)
        page_size = min(max(int(request.query_params.get('page_size', SALES_PAGE_SIZE)), 0), SALES_PAGE_MAX)
    except ValueError:
        raise ValidationError(gettext('Page and page size must be numbers.'))
    return page, page_size


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@on_replica
def sales(request):
    """The period's totals, by product and by payment method, and its sales
    one page at a time: ?page= (from 1) and ?page_size= (default
    SALES_PAGE_SIZE, at most SALES_PAGE_MAX; 0 for totals only). The totals
    always cover the whole period. ?top=N keeps only the N best-selling
    products in by_product."""
    page, page_size = _page(request)
    stores = stores_for(request)
    start, end = date_range(request)
    qs = Sale.objects.filter(
        on_days('completed_at', start, end),
        store__in=stores, status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED],
    )
    if is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    # Lines are aggregated from a subquery of the same sales, not a list of
    # their ids: a long date range would otherwise send thousands of ids
    # back to the database in one IN (...).
    completed_ids = qs.filter(status=Sale.Status.COMPLETED).values('pk')

    # Totals over the whole period from plain values, one tuple per sale
    # (VAT is rounded per sale, as on its receipt, so it is summed here).
    by_method = {}
    count, gross, vat_sum, void_total, void_count, missing_efd = 0, ZERO, ZERO, ZERO, 0, 0
    discounts, on_credit = ZERO, ZERO
    totals = sale_totals(qs).values_list(
        'status', 'sale_total', 'standard_total', 'sale_discount', 'credit_amount', 'efd_receipt_no',
        'payment_method__name', 'payment_method__implementation').order_by()
    for status_, sale_total, standard_total, discount, credit, efd, method_name, implementation in totals:
        count += 1
        total = money(sale_total)
        if status_ == Sale.Status.VOIDED:
            void_count += 1
            void_total += total
            continue
        gross += total
        vat_sum += vat(standard_total)
        discounts += discount or ZERO
        on_credit += credit
        if not efd:
            missing_efd += 1
        for name, _impl, amount in split_payment(method_name, implementation, total, credit):
            method = by_method.setdefault(name, {'payment_method': name, 'count': 0, 'total': ZERO})
            method['count'] += 1
            method['total'] += amount

    # The rows of one page only, with just the columns they show.
    num_pages = max(1, (count + page_size - 1) // page_size) if page_size else 0
    page = min(page, num_pages) if num_pages else 1
    rows = []
    if page_size:
        store_names = dict(stores.values_list('id', 'name'))
        page_qs = sale_totals(qs.select_related('cashier', 'payment_method').only(
            'id', 'number', 'completed_at', 'store_id', 'status', 'payment_reference', 'efd_receipt_no',
            'customer_name', 'void_reason', 'credit_amount',
            'cashier__username', 'cashier__first_name', 'cashier__last_name',
            'payment_method__name', 'payment_method__implementation',
        )).order_by('completed_at', 'pk')[(page - 1) * page_size:page * page_size]
        rows = [{
            'id': s.id, 'number': s.number, 'completed_at': s.completed_at, 'store': store_names[s.store_id],
            'cashier': display_name(s.cashier),
            'payment_method': s.payment_method.name if s.payment_method else '',
            'payment_reference': s.payment_reference, 'efd_receipt_no': s.efd_receipt_no,
            'customer_name': s.customer_name, 'status': s.status, 'void_reason': s.void_reason,
            'total': money(s.sale_total), 'vat': vat(s.standard_total), 'discount': money(s.sale_discount or ZERO),
            'credit': money(s.credit_amount),
        } for s in page_qs]

    by_product = (
        SaleLine.objects.filter(sale__in=completed_ids).values('batch__product_id', 'batch__product__name', 'batch__product__uom__name')
        .annotate(qty_total=Sum('qty'), value=Sum('amount', output_field=MONEY_FIELD))
        .order_by('-value')
    )
    top = request.query_params.get('top')
    if top:
        if not top.isdigit():
            raise ValidationError({'top': gettext('Must be a number.')})
        by_product = by_product[:int(top)]
    return Response({
        'start': start, 'end': end,
        'summary': {
            'sales_count': count - void_count, 'gross_total': money(gross), 'vat_total': money(vat_sum),
            'void_count': void_count, 'void_total': money(void_total), 'missing_efd_count': missing_efd,
            'discount_total': money(discounts), 'credit_total': money(on_credit),
            'by_payment_method': [{**m, 'total': money(m['total'])} for m in by_method.values()],
        },
        'sales': rows,
        'sales_page': {'page': page, 'page_size': page_size, 'count': count, 'num_pages': num_pages},
        'by_product': [
            {'product': r['batch__product__name'], 'unit': r['batch__product__uom__name'], 'qty': r['qty_total'], 'value': money(r['value'])} for r in by_product
        ],
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
@on_replica
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
            on_days('sale__completed_at', start, end),
            sale__store__in=stores, sale__status=Sale.Status.COMPLETED,
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
@on_replica
def shifts(request):
    stores = stores_for(request)
    start, end = date_range(request)
    qs = Shift.objects.filter(
        on_days('opened_at', start, end), store__in=stores,
    ).select_related('store', 'cashier').order_by('opened_at')
    if is_cashier_only(request.user, stores):
        qs = qs.filter(cashier=request.user)
    # Each Z-report needs the shift's sales, their lines and its credit
    # repayments: prefetched for every shift at once, not three queries each.
    qs = shift_service.with_summary_data(qs)
    return Response({
        'start': start, 'end': end,
        'shifts': [
            {
                'id': s.id, 'store': s.store.name, 'cashier': display_name(s.cashier),
                'opened_at': s.opened_at, 'closed_at': s.closed_at, 'closing_note': s.closing_note,
                **shift_service.summary(s),
            }
            for s in qs
        ],
    })


@api_view(['GET'])
@permission_classes([roles(*MANAGEMENT_ROLES)])
@on_replica
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
@on_replica
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
@on_replica
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
@on_replica
def losses(request):
    """Every stock movement that isn't a sale, purchase or transfer —
    write-offs and stock-count corrections — valued at cost."""
    stores = stores_for(request)
    start, end = date_range(request)
    entries = (
        StockLedger.objects.filter(
            on_days('created_at', start, end),
            store__in=stores, ledger_type__in=_LOSS_TYPES,
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
