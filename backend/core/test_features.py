from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from credit.models import Customer
from inventory.models import StockBatch
from payments.models import PaymentMethod
from pricing.models import Price

from .features import feature_values, is_enabled, set_feature
from .models import Entity, Role, Store, StoreRole, User


class FeatureSwitchTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.shop = Store.objects.create(entity=self.entity, name='Shop')
        self.warehouse = Store.objects.create(entity=self.entity, name='Warehouse')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.cashier, store=self.warehouse, role=Role.CASHIER)

    def test_defaults_apply_with_no_settings_saved(self):
        self.assertTrue(is_enabled('pos_sale', store=self.shop))
        self.assertTrue(is_enabled('customer_credit', store=self.shop))

    def test_a_store_setting_overrides_the_firm(self):
        set_feature('pos_sale', False, entity=self.entity, store=self.warehouse)
        self.assertFalse(is_enabled('pos_sale', store=self.warehouse))
        self.assertTrue(is_enabled('pos_sale', store=self.shop))
        # As seen from the whole firm, a store-level feature is on if any store has it.
        self.assertTrue(feature_values(self.entity)['pos_sale'])

    def test_admin_switches_a_feature_and_it_is_audited(self):
        from audit.models import AuditEvent

        self.client.force_authenticate(self.admin)
        response = self.client.patch('/api/core/features/', {
            'key': 'pos_sale', 'store': str(self.warehouse.id), 'enabled': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        pos = next(f for f in response.data['features'] if f['key'] == 'pos_sale')
        self.assertEqual(pos['stores'], {str(self.shop.id): True, str(self.warehouse.id): False})
        self.assertTrue(AuditEvent.objects.filter(summary='Point of sale switched off at Warehouse').exists())

    def test_only_an_admin_can_switch_features(self):
        self.client.force_authenticate(self.cashier)
        response = self.client.patch('/api/core/features/', {'key': 'pos_sale', 'enabled': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_me_reports_features_per_store(self):
        set_feature('pos_sale', False, entity=self.entity, store=self.warehouse)
        self.client.force_authenticate(self.cashier)
        roles = self.client.get('/api/core/users/me/').data['store_roles']
        self.assertFalse(roles[0]['features']['pos_sale'])

    def test_switched_off_point_of_sale_refuses_shifts_and_sales(self):
        set_feature('pos_sale', False, entity=self.entity, store=self.warehouse)
        self.client.force_authenticate(self.cashier)
        response = self.client.post('/api/pos/shifts/', {'store': str(self.warehouse.id), 'opening_float': '0'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Point of sale is switched off at Warehouse', response.data['detail'])
        response = self.client.post('/api/pos/sales/', {'store': str(self.warehouse.id)})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_switched_off_receiving_refuses_invoices(self):
        from receiving.models import Supplier

        set_feature('receiving_invoice', False, entity=self.entity, store=self.shop)
        supplier = Supplier.objects.create(entity=self.entity, name='MSD')
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(self.shop.id), 'supplier': str(supplier.id), 'invoice_number': 'X1',
            'received_date': '2026-10-01'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_store_without_credit_cannot_sell_on_credit(self):
        set_feature('customer_credit', False, entity=self.entity, store=self.shop)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Packet', unit_value=1)
        sugar = Product.objects.create(entity=self.entity, name='Sugar 1kg', uom=uom)
        Price.objects.create(entity=self.entity, product=sugar, unit_price=Decimal('3000'))
        StockBatch.objects.create(store=self.shop, product=sugar, expiry_date=date(2030, 1, 1), qty_on_hand=5)
        customer = Customer.objects.create(entity=self.entity, name='Mama Neema')
        cash, _ = PaymentMethod.objects.get_or_create(implementation='cash', defaults={'name': 'Cash', 'is_active': True})
        self.client.force_authenticate(self.admin)
        self.client.post('/api/pos/shifts/', {'store': str(self.shop.id), 'opening_float': '0'})
        sale = self.client.post('/api/pos/sales/', {
            'store': str(self.shop.id), 'items': [{'product': str(sugar.id), 'qty': '1'}]}, format='json').data
        response = self.client.post(f'/api/pos/sales/{sale["id"]}/complete/', {
            'payment_method': str(cash.id), 'customer': str(customer.id), 'credit_amount': '3000'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('does not sell on credit', response.data['detail'])

    def test_switched_off_analytics_refuses_the_api(self):
        set_feature('analytics_dashboards', False, entity=self.entity)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/analytics/query/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/analytics/visualizations/').status_code, status.HTTP_403_FORBIDDEN)


class SingleStoreFeatureTests(APITestCase):
    """Transfers need a second store, so a single shop has them off
    regardless of its switch — and gets its own choice back if it grows."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Mama Neema Duka', store_mode=Entity.StoreMode.SINGLE)
        self.store = self.entity.ensure_single_store()
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)

    def test_transfer_is_off_for_a_single_shop(self):
        self.assertFalse(is_enabled('transfer', entity=self.entity))
        self.assertFalse(is_enabled('transfer', store=self.store))
        self.assertFalse(feature_values(self.entity)['transfer'])
        self.assertTrue(feature_values(self.entity)['pos_sale'])

    def test_switch_cannot_turn_transfer_on(self):
        response = self.client.patch('/api/core/features/', {'key': 'transfer', 'store': None, 'enabled': True}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(is_enabled('transfer', entity=self.entity))

    def test_features_screen_says_why(self):
        response = self.client.get('/api/core/features/')

        by_key = {f['key']: f for f in response.data['features']}
        self.assertIn('single shop', by_key['transfer']['unavailable'])
        self.assertIsNone(by_key['pos_sale']['unavailable'])

    def test_moving_to_multiple_stores_brings_transfer_back(self):
        self.entity.store_mode = Entity.StoreMode.MULTI
        self.entity.save()

        self.assertTrue(is_enabled('transfer', entity=self.entity))
