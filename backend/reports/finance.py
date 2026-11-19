"""Owner-facing money reports: what is owed to suppliers, what each
product actually earns, and what sells versus what sits on the shelf."""

from datetime import timedelta

from django.db.models import Q, Sum
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from catalog.models import Product
from core.models import Role
from core.money import VAT_RATE, ZERO, money
from core.permissions import roles
from enquiry.models import Transfer
from pos.models import Sale, SaleLine
from receiving.models import ReceivingInvoice

from .queries import MANAGEMENT_ROLES, date_range, day_start, on_days, stores_for, usable_stock

_MANAGERS = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)
_BUCKETS = ('not_due', 'overdue_1_30', 'overdue_31_60', 'overdue_61_plus')


def _bucket(days_late):
    if days_late <= 0:
        return 'not_due'
    if days_late <= 30:
        return 'overdue_1_30'
    if days_late <= 60:
        return 'overdue_31_60'
    return 'overdue_61_plus'


@api_view(['GET'])
@permission_classes([roles(*_MANAGERS)])
def payables(request):
    """What is still owed to each supplier, aged by how overdue it is."""
    stores = stores_for(request)
    today = timezone.localdate()
    invoices = (
        ReceivingInvoice.objects.filter(store__in=stores, status=ReceivingInvoice.Status.RECEIVED)
        .select_related('store', 'supplier').prefetch_related('lines', 'payments')
    )
    rows, by_supplier = [], {}
    for inv in invoices:
        balance = money(inv.balance)
        if balance <= 0:
            continue
        due = inv.due_date or inv.received_date
        late = (today - due).days
        bucket = _bucket(late)
        rows.append({
            'id': inv.id, 'store': inv.store.name, 'supplier': inv.supplier.name,
            'invoice_number': inv.invoice_number, 'received_date': inv.received_date, 'due_date': due,
            'days_overdue': max(late, 0), 'total': money(inv.total), 'paid': money(inv.amount_paid),
            'balance': balance, 'bucket': bucket,
        })
        supplier = by_supplier.setdefault(inv.supplier.name, {
            'supplier': inv.supplier.name, 'balance': ZERO, **{b: ZERO for b in _BUCKETS}})
        supplier['balance'] += balance
        supplier[bucket] += balance
    rows.sort(key=lambda r: (r['due_date'], r['supplier']))
    return Response({
        'date': today,
        'summary': {
            'owed': money(sum((r['balance'] for r in rows), ZERO)),
            'overdue': money(sum((r['balance'] for r in rows if r['bucket'] != 'not_due'), ZERO)),
            'invoice_count': len(rows),
        },
        'by_supplier': sorted(by_supplier.values(), key=lambda s: -s['balance']),
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([roles(*_MANAGERS)])
def margin(request):
    """Gross margin per product: sales without VAT, less what the units
    sold cost (each sold batch's own cost)."""
    stores = stores_for(request)
    start, end = date_range(request)
    lines = (
        SaleLine.objects.filter(on_days('sale__completed_at', start, end),
                                sale__store__in=stores, sale__status=Sale.Status.COMPLETED)
        .select_related('batch__product__uom')
    )
    by_product = {}
    for line in lines:
        net = line.amount / (1 + VAT_RATE) if line.vat_class == Product.VatClass.STANDARD else line.amount
        row = by_product.setdefault(line.batch.product_id, {
            'product': line.batch.product.name, 'unit': line.batch.product.uom.name,
            'qty': ZERO, 'sales_ex_vat': ZERO, 'cost': ZERO, 'cost_unknown_qty': ZERO,
        })
        row['qty'] += line.qty
        row['sales_ex_vat'] += net
        row['cost'] += line.qty * line.batch.unit_cost
        if line.batch.unit_cost == 0:
            row['cost_unknown_qty'] += line.qty
    rows = []
    for row in by_product.values():
        sales, cost = money(row['sales_ex_vat']), money(row['cost'])
        rows.append({**row, 'sales_ex_vat': sales, 'cost': cost, 'margin': sales - cost,
                     'margin_pct': round(float((sales - cost) / sales * 100), 1) if sales else None})
    rows.sort(key=lambda r: -r['margin'])
    sales = sum((r['sales_ex_vat'] for r in rows), ZERO)
    cost = sum((r['cost'] for r in rows), ZERO)
    return Response({
        'start': start, 'end': end,
        'summary': {
            'sales_ex_vat': money(sales), 'cost': money(cost), 'margin': money(sales - cost),
            'margin_pct': round(float((sales - cost) / sales * 100), 1) if sales else None,
            'products_without_cost': sum(1 for r in rows if r['cost_unknown_qty']),
        },
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([roles(*MANAGEMENT_ROLES)])
def movers(request):
    """What sells and what sits: units sold over the last ?days= (default
    90), the average per day, and how many days the current stock lasts at
    that rate. Products with stock but no sales in the period are dead stock."""
    stores = stores_for(request)
    today = timezone.localdate()
    try:
        days = min(max(int(request.query_params.get('days', 90)), 7), 365)
    except ValueError:
        raise ValidationError({'days': gettext('Must be a number.')})
    since = today - timedelta(days=days)
    sold = dict(
        SaleLine.objects.filter(sale__store__in=stores, sale__status=Sale.Status.COMPLETED,
                                sale__completed_at__gte=day_start(since + timedelta(days=1)))
        .values('batch__product_id').annotate(q=Sum('qty')).values_list('batch__product_id', 'q')
    )
    stock = {}
    for (_store_id, product_id), (usable, _expired, _cost) in usable_stock(stores, today).items():
        stock[product_id] = stock.get(product_id, ZERO) + usable
    products = Product.objects.select_related('uom').in_bulk(set(sold) | set(stock))
    rows = []
    for pid, product in products.items():
        qty = sold.get(pid) or ZERO
        on_hand = stock.get(pid, ZERO)
        per_day = qty / days
        rows.append({
            'product': product.name, 'unit': product.uom.name, 'sold': qty, 'per_day': round(float(per_day), 2),
            # stock x days / sold, not stock / per_day: dividing first rounds 282 down to 281.
            'on_hand': on_hand, 'days_of_cover': int(on_hand * days / qty) if qty else None,
        })
    rows.sort(key=lambda r: -r['sold'])
    fast_cut = max(1, sum(1 for r in rows if r['sold'] > 0) // 5)
    for i, r in enumerate(rows):
        if r['sold'] == 0:
            r['class'] = 'dead' if r['on_hand'] > 0 else 'none'
        elif i < fast_cut:
            r['class'] = 'fast'
        elif r['days_of_cover'] is not None and r['days_of_cover'] > 180:
            r['class'] = 'slow'
        else:
            r['class'] = 'normal'
    rows = [r for r in rows if r['class'] != 'none']
    return Response({
        'date': today, 'days': days,
        'summary': {c: sum(1 for r in rows if r['class'] == c) for c in ('fast', 'slow', 'dead')},
        'rows': rows,
    })


@api_view(['GET'])
@permission_classes([roles(*_MANAGERS)])
def transfers(request):
    """Stock moved between stores in the period, valued at cost, plus what
    is still in transit, short deliveries waiting to be resolved, and (hub
    firms) what each branch still owes the main store — regardless of
    period, since an unpaid balance is owed until it is paid."""
    stores = stores_for(request)
    start, end = date_range(request)
    base = (Transfer.objects.filter(Q(from_store__in=stores) | Q(to_store__in=stores))
            .select_related('from_store', 'to_store').prefetch_related('lines__batch__product'))
    in_period = base.filter(on_days('dispatched_at', start, end)).exclude(
        status=Transfer.Status.CANCELLED).order_by('dispatched_at')

    def value(t):
        return money(sum((line.qty * line.unit_cost for line in t.lines.all()), ZERO))

    rows = [{
        'id': t.id, 'number': t.number, 'date': t.dispatched_at, 'from_store': t.from_store.name,
        'to_store': t.to_store.name, 'status': t.get_status_display(), 'mode': t.mode,
        'items': ', '.join(f'{line.batch.product.name} x{line.qty.normalize():f}' for line in t.lines.all()),
        'value': value(t), 'amount': t.amount, 'balance': money(t.balance),
    } for t in in_period]

    owed = {}
    for t in base.filter(mode=Transfer.Mode.HUB, status=Transfer.Status.RECEIVED, paid_at__isnull=True):
        if t.balance > 0:
            branch = owed.setdefault(t.to_store.name, {'store': t.to_store.name, 'balance': ZERO, 'count': 0})
            branch['balance'] += t.balance
            branch['count'] += 1
    return Response({
        'start': start, 'end': end,
        'summary': {
            'count': len(rows),
            'value': money(sum((r['value'] for r in rows), ZERO)),
            'in_transit': base.filter(status=Transfer.Status.DISPATCHED).count(),
            'short_deliveries': base.filter(status=Transfer.Status.DISCREPANCY).count(),
            'branches_owe': money(sum((b['balance'] for b in owed.values()), ZERO)),
        },
        'owed_by_branch': sorted(({**b, 'balance': money(b['balance'])} for b in owed.values()),
                                 key=lambda b: -b['balance']),
        'rows': rows,
    })
