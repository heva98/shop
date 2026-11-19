from datetime import timedelta
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status

from core.models import Entity, Role, Store, StoreRole, User
from credit.models import Customer
from credit.services import receive_payment
from inventory.models import StockBatch, StoreProduct
from pos.models import Sale, Shift
from pos.services import shifts
from pos.tests import PosTestBase
from reports.queries import usable_stock


class ReportTests(PosTestBase):
    def setUp(self):
        super().setUp()
        self.open_shift()
        kept = self.new_sale(qty='2')        # 2,360
        self.complete(kept['id'])
        voided = self.new_sale(qty='1')      # 1,180, voided below
        self.complete(voided['id'])
        self.client.force_authenticate(self.manager)
        self.client.post(f'/api/pos/sales/{voided["id"]}/void/', {'reason': 'Duplicate'})
        self.client.post('/api/pos/sales/', {
            'store': str(self.store.id), 'items': [{'product': str(self.product.id), 'qty': '1'}],
        }, format='json')                    # left open: never counted

    def test_sales_report_counts_only_completed_sales(self):
        response = self.client.get('/api/reports/sales/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        summary = response.data['summary']
        self.assertEqual(summary['sales_count'], 1)
        self.assertEqual(summary['gross_total'], Decimal('2360.00'))
        self.assertEqual(summary['vat_total'], Decimal('360.00'))
        self.assertEqual(summary['void_count'], 1)
        self.assertEqual(summary['missing_efd_count'], 1)
        self.assertEqual(len(response.data['sales']), 2)
        self.assertEqual(response.data['by_product'][0]['qty'], Decimal('2'))

    def test_dashboard_reflects_real_data(self):
        StoreProduct.objects.create(store=self.store, product=self.product, reorder_level=Decimal('100'))
        StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='OLD',
            expiry_date=timezone.localdate() - timedelta(days=1), qty_on_hand=Decimal('3'),
        )
        response = self.client.get('/api/reports/dashboard/', {'store': str(self.store.id)})
        self.assertEqual(response.data['sales_today_total'], Decimal('2360.00'))
        self.assertEqual(response.data['sales_today_count'], 1)
        self.assertEqual(response.data['sales_missing_efd'], 1)
        self.assertEqual(response.data['low_stock_count'], 1)
        self.assertEqual(response.data['expired_on_shelf_count'], 1)
        self.assertEqual(response.data['open_shifts_count'], 1)

    def test_cashier_cannot_read_another_stores_reports(self):
        other_entity = Entity.objects.create(name='Firm B')
        other = Store.objects.create(entity=other_entity, name='B')
        self.client.force_authenticate(self.cashier)
        response = self.client.get('/api/reports/sales/', {'store': str(other.id)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cashier_sees_only_own_sales_and_no_stock_valuation(self):
        other_cashier = User.objects.create_user(username='c2', password='x', entity=self.entity)
        StoreRole.objects.create(user=other_cashier, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(other_cashier)
        response = self.client.get('/api/reports/sales/', {'store': str(self.store.id)})
        self.assertEqual(response.data['sales'], [])
        self.assertEqual(self.client.get('/api/reports/stock/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/reports/purchases/').status_code, status.HTTP_403_FORBIDDEN)

    def test_losses_report_values_write_offs_at_cost(self):
        from inventory.services import adjustments
        self.expires_later.unit_cost = Decimal('400')
        self.expires_later.save()
        adjustments.apply(batch=self.expires_later, qty_delta=Decimal('-2'), reason='damaged',
                          note='Dropped', user=self.manager)
        response = self.client.get('/api/reports/losses/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['summary']['value'], Decimal('-800.00'))
        self.assertEqual(response.data['rows'][0]['note'], 'Dropped')


    def _shifts_report(self):
        self.client.force_authenticate(self.manager)
        response = self.client.get('/api/reports/shifts/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data['shifts']

    def _closed_shift_with_a_sale(self, user):
        shift_id = self.open_shift(user)
        sale = self.new_sale(qty='1')
        self.assertEqual(self.complete(sale['id']).status_code, status.HTTP_200_OK)
        self.client.post(f'/api/pos/shifts/{shift_id}/close/', {'counted_cash': '11000'})

    def test_shifts_report_matches_each_shifts_own_z_report(self):
        customer = Customer.objects.create(entity=self.entity, name='Mama Neema', phone='255712000001')
        receive_payment(customer=customer, store=self.store, amount=Decimal('500'),
                                payment_method=self.cash, user=self.cashier)
        self._closed_shift_with_a_sale(self.manager)
        rows = self._shifts_report()
        self.assertEqual(len(rows), 2)
        for row in rows:
            expected = shifts.summary(Shift.objects.get(pk=row['id']))
            self.assertEqual({key: row[key] for key in expected}, expected)
        cashier_row = next(r for r in rows if r['cashier'] == 'cashier')
        self.assertEqual(cashier_row['cash_repayments'], Decimal('500.00'))
        self.assertEqual(cashier_row['void_count'], 1)

    def test_shifts_report_queries_do_not_grow_with_the_number_of_shifts(self):
        self._shifts_report()  # warm up anything cached per process
        with CaptureQueriesContext(connection) as one_shift:
            self._shifts_report()
        for i in range(3):
            user = User.objects.create_user(username=f'extra{i}', password='x', entity=self.entity)
            StoreRole.objects.create(user=user, store=self.store, role=Role.CASHIER)
            self._closed_shift_with_a_sale(user)
        with CaptureQueriesContext(connection) as four_shifts:
            rows = self._shifts_report()
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(four_shifts), len(one_shift))


    def test_usable_stock_matches_summing_each_batch(self):
        today = timezone.localdate()
        for no, expiry, qty, cost in [('EXP', today - timedelta(days=2), '4.50', '120.25'),
                                      ('NONE', None, '0.75', '0'), ('TODAY', today, '3', '99.99')]:
            StockBatch.objects.create(store=self.store, product=self.product, batch_no=no,
                                      expiry_date=expiry, qty_on_hand=Decimal(qty), unit_cost=Decimal(cost))
        expected = {}
        for b in StockBatch.objects.filter(store=self.store, qty_on_hand__gt=0):
            row = expected.setdefault((b.store_id, b.product_id), [Decimal('0')] * 3)
            row[1 if b.expiry_date is not None and b.expiry_date < today else 0] += b.qty_on_hand
            row[2] += b.qty_on_hand * b.unit_cost
        actual = usable_stock(Store.objects.filter(pk=self.store.pk), today)
        self.assertEqual(dict(actual), expected)
        self.assertEqual([str(v) for v in actual[(self.store.id, self.product.id)]],
                         [str(v) for v in expected[(self.store.id, self.product.id)]])


    def test_role_limited_reports_cover_only_stores_where_the_role_is_held(self):
        branch = Store.objects.create(entity=self.entity, name='Branch')
        StockBatch.objects.create(store=branch, product=self.product, batch_no='BR', qty_on_hand=Decimal('7'))
        keeper = User.objects.create_user(username='keeper', password='x', entity=self.entity)
        StoreRole.objects.create(user=keeper, store=self.store, role=Role.STOREKEEPER)
        StoreRole.objects.create(user=keeper, store=branch, role=Role.CASHIER)
        self.client.force_authenticate(keeper)
        response = self.client.get('/api/reports/stock/')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual({row['store'] for row in response.data['rows']}, {'A'})
        self.assertEqual(self.client.get('/api/reports/stock/', {'store': str(branch.id)}).status_code,
                         status.HTTP_403_FORBIDDEN)
        # A report open to every role still covers both stores.
        sales = self.client.get('/api/reports/sales/')
        self.assertEqual(sales.status_code, status.HTTP_200_OK)


class ReportDayBoundaryTests(PosTestBase):
    """Reports pick a day's rows by time range in the shop's time zone
    (reports.queries.on_days): a sale just before midnight belongs to
    that day, one just after to the next."""

    def setUp(self):
        super().setUp()
        self.open_shift()
        today = timezone.localdate()
        midnight = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
        for when in (midnight - timedelta(minutes=1), midnight):
            sale = self.new_sale(qty='1')
            self.complete(sale['id'])
            Sale.objects.filter(pk=sale['id']).update(completed_at=when)
        self.client.force_authenticate(self.manager)

    def test_dashboard_counts_only_todays_sales(self):
        data = self.client.get('/api/reports/dashboard/', {'store': str(self.store.id)}).data
        self.assertEqual(data['sales_today_count'], 1)
        self.assertEqual(data['sales_today_total'], Decimal('1180.00'))

    def test_sales_report_takes_whole_days(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        one_day = self.client.get('/api/reports/sales/', {'start': yesterday, 'end': yesterday}).data
        self.assertEqual(one_day['summary']['sales_count'], 1)
        both = self.client.get('/api/reports/sales/', {'start': yesterday}).data
        self.assertEqual(both['summary']['sales_count'], 2)

    def test_sales_report_pages_its_rows_but_totals_the_whole_period(self):
        yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
        first = self.client.get('/api/reports/sales/', {'start': yesterday, 'page_size': 1}).data
        second = self.client.get('/api/reports/sales/', {'start': yesterday, 'page_size': 1, 'page': 2}).data
        self.assertEqual(first['sales_page'], {'page': 1, 'page_size': 1, 'count': 2, 'num_pages': 2})
        self.assertEqual(len(first['sales']), 1)
        self.assertLess(first['sales'][0]['completed_at'], second['sales'][0]['completed_at'])
        for data in (first, second):
            self.assertEqual(data['summary']['sales_count'], 2)
            self.assertEqual(data['summary']['gross_total'], Decimal('2360.00'))
        totals_only = self.client.get('/api/reports/sales/', {'start': yesterday, 'page_size': 0, 'top': 1}).data
        self.assertEqual(totals_only['sales'], [])
        self.assertEqual(len(totals_only['by_product']), 1)
        self.assertEqual(totals_only['summary']['sales_count'], 2)
        past_the_end = self.client.get('/api/reports/sales/', {'start': yesterday, 'page_size': 1, 'page': 9}).data
        self.assertEqual(past_the_end['sales_page']['page'], 2)
        self.assertEqual(self.client.get('/api/reports/sales/', {'page': 'x'}).status_code, status.HTTP_400_BAD_REQUEST)

    def test_purchases_report_answers(self):
        self.assertEqual(self.client.get('/api/reports/purchases/').status_code, status.HTTP_200_OK)
