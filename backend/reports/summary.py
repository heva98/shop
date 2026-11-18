"""GET /api/reports/summary/?period=today|week|month|last_month[&store=<id>]

The Reports home page in one request: the answers a shop owner looks for
first, in plain numbers, without choosing a report or dates.

    sales          total, number of sales, average sale, and the same
                   length of time just before, to compare
    profit         sales without VAT less what the goods cost
    by_day         sales per day across the period (not for "today")
    payments       how the money came in
    best_sellers   top 5 products by value
    running_low    products at or below their reorder level, or out
    not_selling    products in stock with no sale in the last 30 days
    customers_owe  customer credit still unpaid (credit is shop-wide)
    you_owe        unpaid supplier invoices

Each number matches the detailed report it summarizes (sales, margin,
stock, movers, payables)."""

from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from catalog.models import Product
from core.models import Role
from core.money import VAT_RATE, ZERO, money
from core.permissions import roles
from credit.models import Customer, with_balances
from inventory.models import StoreProduct
from pos.models import Sale, SaleLine
from receiving.models import ReceivingInvoice

from .queries import sale_totals, stores_for, usable_stock

PERIODS = ('today', 'week', 'month', 'last_month')
NOT_SELLING_DAYS = 30


def period_range(period, today):
    """(start, end, previous_start, previous_end), inclusive. The previous
    range is the same length of time just before: yesterday, last week, or
    the same days of last month (1–18 Nov against 1–18 Oct)."""
    if period == 'today':
        return today, today, today - timedelta(days=1), today - timedelta(days=1)
    if period == 'week':
        start = today - timedelta(days=today.weekday())  # Monday
        return start, today, start - timedelta(days=7), today - timedelta(days=7)
    first = today.replace(day=1)
    last_month_end = first - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    if period == 'month':
        prev_end = min(last_month_start + timedelta(days=today.day - 1), last_month_end)
        return first, today, last_month_start, prev_end
    before_end = last_month_start - timedelta(days=1)
    return last_month_start, last_month_end, before_end.replace(day=1), before_end


def _completed(stores, start, end):
    return Sale.objects.filter(store__in=stores, status=Sale.Status.COMPLETED,
                               completed_at__date__gte=start, completed_at__date__lte=end)


@api_view(['GET'])
@permission_classes([roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)])
def summary(request):
    stores = stores_for(request)
    period = request.query_params.get('period') or 'today'
    if period not in PERIODS:
        raise ValidationError({'period': gettext('Choose today, week, month or last_month.')})
    today = timezone.localdate()
    start, end, prev_start, prev_end = period_range(period, today)

    # Sales and profit, from the lines (what the sales and margin reports add up).
    lines = (SaleLine.objects.filter(sale__in=_completed(stores, start, end))
             .values('amount', 'qty', 'vat_class', 'batch__unit_cost', 'batch__product_id',
                     'batch__product__name', 'batch__product__uom__name'))
    total = sales_ex_vat = cost = ZERO
    by_product, unknown_cost = {}, set()
    for line in lines:
        amount = line['amount']
        total += amount
        sales_ex_vat += amount / (1 + VAT_RATE) if line['vat_class'] == Product.VatClass.STANDARD else amount
        cost += line['qty'] * line['batch__unit_cost']
        pid = line['batch__product_id']
        if line['batch__unit_cost'] == 0:
            unknown_cost.add(pid)
        row = by_product.setdefault(pid, {'product': line['batch__product__name'],
                                          'unit': line['batch__product__uom__name'], 'qty': ZERO, 'value': ZERO})
        row['qty'] += line['qty']
        row['value'] += amount
    count = _completed(stores, start, end).count()
    previous = (SaleLine.objects.filter(sale__in=_completed(stores, prev_start, prev_end))
                .aggregate(t=Sum('amount'))['t'] or ZERO)

    payments = {}
    for sale in sale_totals(_completed(stores, start, end).select_related('payment_method')):
        for name, _impl, amount in sale.payment_split(sale.sale_total or ZERO):
            payments[name] = payments.get(name, ZERO) + amount

    by_day = []
    if start != end:
        daily = dict(
            _completed(stores, start, end).annotate(day=TruncDate('completed_at')).values('day')
            .annotate(t=Sum('lines__amount')).values_list('day', 't'))
        by_day = [{'date': start + timedelta(days=i), 'total': money(daily.get(start + timedelta(days=i)))}
                  for i in range((end - start).days + 1)]

    # Stock as of today, whatever the period (as the stock report).
    levels = usable_stock(stores, today)
    names = Product.objects.select_related('uom').in_bulk({pid for (_s, pid) in levels}
                                                         | set(StoreProduct.objects.filter(store__in=stores, enabled=True)
                                                               .values_list('product_id', flat=True)))
    running_low = []
    for sp in StoreProduct.objects.filter(store__in=stores, enabled=True).select_related('store'):
        usable = levels.get((sp.store_id, sp.product_id), [ZERO])[0]
        if usable <= sp.reorder_level and sp.product_id in names:
            product = names[sp.product_id]
            running_low.append({'product': product.name, 'unit': product.uom.name, 'store': sp.store.name,
                                'qty': usable, 'reorder_level': sp.reorder_level, 'status': 'out' if usable <= 0 else 'low'})
    running_low.sort(key=lambda r: (r['status'] != 'out', r['product']))

    sold_recently = set(SaleLine.objects.filter(
        sale__store__in=stores, sale__status=Sale.Status.COMPLETED,
        sale__completed_at__date__gt=today - timedelta(days=NOT_SELLING_DAYS),
    ).values_list('batch__product_id', flat=True).distinct())
    on_hand = {}
    for (_store, pid), (usable, _expired, _cost) in levels.items():
        on_hand[pid] = on_hand.get(pid, ZERO) + usable
    not_selling = sorted(
        ({'product': names[pid].name, 'unit': names[pid].uom.name, 'qty': qty}
         for pid, qty in on_hand.items() if qty > 0 and pid not in sold_recently and pid in names),
        key=lambda r: -r['qty'])

    customers = with_balances(Customer.objects.filter(entity_id__in=stores.values('entity_id'), is_active=True))
    owing = [c.owing for c in customers if c.owing > 0]
    invoices = (ReceivingInvoice.objects.filter(store__in=stores, status=ReceivingInvoice.Status.RECEIVED)
                .prefetch_related('lines', 'payments'))
    supplier_owed = supplier_overdue = ZERO
    for inv in invoices:
        balance = inv.balance
        if balance > 0:
            supplier_owed += balance
            if (inv.due_date or inv.received_date) < today:
                supplier_overdue += balance

    margin = money(sales_ex_vat) - money(cost)
    return Response({
        'period': period, 'start': start, 'end': end, 'previous_start': prev_start, 'previous_end': prev_end,
        'sales': {'total': money(total), 'count': count, 'average': money(total / count) if count else money(0),
                  'previous_total': money(previous)},
        'profit': {'sales_ex_vat': money(sales_ex_vat), 'cost': money(cost), 'margin': margin,
                   'margin_pct': round(float(margin / money(sales_ex_vat) * 100), 1) if sales_ex_vat else None,
                   'products_without_cost': len(unknown_cost)},
        'by_day': by_day,
        'payments': [{'name': n, 'total': money(v)} for n, v in sorted(payments.items(), key=lambda kv: -kv[1])],
        'best_sellers': [{**r, 'value': money(r['value'])}
                         for r in sorted(by_product.values(), key=lambda r: -r['value'])[:5]],
        'running_low': {'count': len(running_low), 'out_count': sum(1 for r in running_low if r['status'] == 'out'),
                        'rows': running_low[:8]},
        'not_selling': {'days': NOT_SELLING_DAYS, 'count': len(not_selling), 'rows': not_selling[:5]},
        'customers_owe': {'total': money(sum(owing, ZERO)), 'count': len(owing)},
        'you_owe': {'total': money(supplier_owed), 'overdue': money(supplier_overdue)},
    })
