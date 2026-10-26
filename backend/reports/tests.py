from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status

from core.models import Entity, Role, Store, StoreRole, User
from inventory.models import StockBatch, StoreProduct
from pos.tests import PosTestBase


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
        from inventory.models import StockAdjustment
        self.expires_later.unit_cost = Decimal('400')
        self.expires_later.save()
        StockAdjustment.apply(batch=self.expires_later, qty_delta=Decimal('-2'), reason='damaged',
                              note='Dropped', user=self.manager)
        response = self.client.get('/api/reports/losses/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['summary']['value'], Decimal('-800.00'))
        self.assertEqual(response.data['rows'][0]['note'], 'Dropped')
