from datetime import date, timedelta
from decimal import Decimal

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework import status

from catalog.models import Product
from inventory.models import StockBatch, StoreProduct
from pos.tests import PosTestBase

from .summary import period_range


class PeriodTests(SimpleTestCase):
    def test_periods_and_what_they_are_compared_with(self):
        wed = date(2026, 11, 18)
        self.assertEqual(period_range('today', wed), (wed, wed, date(2026, 11, 17), date(2026, 11, 17)))
        self.assertEqual(period_range('week', wed), (date(2026, 11, 16), wed, date(2026, 11, 9), date(2026, 11, 11)))
        self.assertEqual(period_range('month', wed), (date(2026, 11, 1), wed, date(2026, 10, 1), date(2026, 10, 18)))
        self.assertEqual(period_range('last_month', wed), (date(2026, 10, 1), date(2026, 10, 31), date(2026, 9, 1), date(2026, 9, 30)))
        # 31 March against February, which has no 31st.
        self.assertEqual(period_range('month', date(2026, 3, 31))[2:], (date(2026, 2, 1), date(2026, 2, 28)))


class SummaryTests(PosTestBase):
    def setUp(self):
        super().setUp()
        StockBatch.objects.filter(store=self.store).update(unit_cost=Decimal('600'))
        self.open_shift()
        self.complete(self.new_sale(qty='5')['id'])  # 5 x 1,180 incl. VAT = 5,000 ex VAT; cost 3,000
        self.client.force_authenticate(self.manager)

    def get(self, **params):
        return self.client.get('/api/reports/summary/', {'store': str(self.store.id), **params})

    def test_matches_the_detailed_reports(self):
        response = self.get(period='today')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        d = response.data
        sales = self.client.get('/api/reports/sales/', {'store': str(self.store.id)}).data['summary']
        margin = self.client.get('/api/reports/margin/', {'store': str(self.store.id)}).data['summary']
        self.assertEqual(d['sales']['total'], sales['gross_total'])
        self.assertEqual(d['sales']['count'], sales['sales_count'])
        self.assertEqual(d['profit']['margin'], margin['margin'])
        self.assertEqual(d['profit']['margin_pct'], margin['margin_pct'])
        self.assertEqual(d['best_sellers'][0]['product'], 'Paracetamol')
        self.assertEqual(sum(p['total'] for p in d['payments']), d['sales']['total'])
        self.assertEqual(d['by_day'], [])

    def test_month_has_a_day_by_day_line(self):
        d = self.get(period='month').data
        today = timezone.localdate()
        self.assertEqual(len(d['by_day']), today.day)
        self.assertEqual(d['by_day'][-1]['total'], d['sales']['total'])

    def test_running_low_and_not_selling(self):
        StoreProduct.objects.update_or_create(store=self.store, product=self.product, defaults={'reorder_level': 100})
        idle = Product.objects.create(entity=self.entity, name='Idle syrup', uom=self.product.uom)
        StockBatch.objects.create(store=self.store, product=idle, batch_no='I1',
                                  expiry_date=timezone.localdate() + timedelta(days=300), qty_on_hand=Decimal('9'))
        d = self.get().data
        self.assertIn('Paracetamol', [r['product'] for r in d['running_low']['rows']])
        self.assertEqual([r['product'] for r in d['not_selling']['rows']], ['Idle syrup'])

    def test_bad_period_and_cashiers(self):
        self.assertEqual(self.get(period='year').status_code, status.HTTP_400_BAD_REQUEST)
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.get().status_code, status.HTTP_403_FORBIDDEN)
