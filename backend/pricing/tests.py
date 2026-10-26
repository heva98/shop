from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User

from .models import Bundle, Price


class PricingTenantIsolationTests(APITestCase):
    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A', price_mode=Entity.PriceMode.ENTITY)
        self.entity_b = Entity.objects.create(name='Firm B', price_mode=Entity.PriceMode.ENTITY)
        self.store_a1 = Store.objects.create(entity=self.entity_a, name='A1')
        self.store_a2 = Store.objects.create(entity=self.entity_a, name='A2')
        self.store_b1 = Store.objects.create(entity=self.entity_b, name='B1')

        uom = UnitOfMeasure.objects.create(entity=self.entity_a, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=self.entity_a, name='Amoxicillin', uom=uom)

        self.manager_a1 = User.objects.create_user(username='manager_a1', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.manager_a1, store=self.store_a1, role=Role.STORE_MANAGER)

        self.manager_b1 = User.objects.create_user(username='manager_b1', password='x', entity=self.entity_b)
        StoreRole.objects.create(user=self.manager_b1, store=self.store_b1, role=Role.STORE_MANAGER)

    def test_entity_wide_price_visible_within_entity_not_across(self):
        Price.objects.create(entity=self.entity_a, product=self.product, unit_price='10.00')
        self.client.force_authenticate(self.manager_a1)
        response = self.client.get('/api/pricing/prices/')
        self.assertEqual(len(response.data['results']), 1)

        self.client.force_authenticate(self.manager_b1)
        response = self.client.get('/api/pricing/prices/')
        self.assertEqual(response.data['results'], [])

    def test_cannot_create_price_for_another_entity(self):
        self.client.force_authenticate(self.manager_a1)
        response = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity_b.id), 'product': str(self.product.id), 'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('entity', response.data)

    def test_entity_wide_mode_rejects_store_on_price(self):
        self.client.force_authenticate(self.manager_a1)
        response = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity_a.id), 'store': str(self.store_a1.id),
            'product': str(self.product.id), 'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_store_mode_requires_store_and_scopes_by_it(self):
        self.entity_a.price_mode = Entity.PriceMode.STORE
        self.entity_a.save(update_fields=['price_mode'])

        self.client.force_authenticate(self.manager_a1)
        missing_store = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity_a.id), 'product': str(self.product.id), 'unit_price': '5.00',
        })
        self.assertEqual(missing_store.status_code, status.HTTP_400_BAD_REQUEST)

        price_a1 = Price.objects.create(
            entity=self.entity_a, store=self.store_a1, product=self.product, unit_price='12.00',
        )
        Price.objects.create(entity=self.entity_a, store=self.store_a2, product=self.product, unit_price='15.00')

        response = self.client.get('/api/pricing/prices/')
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {str(price_a1.id)})

    def test_store_mode_rejects_setting_price_for_a_sibling_store(self):
        """manager_a1 has no role at store_a2 (same entity) — same-firm
        isn't enough to set that store's prices."""
        self.entity_a.price_mode = Entity.PriceMode.STORE
        self.entity_a.save(update_fields=['price_mode'])

        self.client.force_authenticate(self.manager_a1)
        response = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity_a.id), 'store': str(self.store_a2.id),
            'product': str(self.product.id), 'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_bundle_scoped_to_entity_and_write_blocked_cross_entity(self):
        Bundle.objects.create(entity=self.entity_a, name='Combo A', price='20.00')
        Bundle.objects.create(entity=self.entity_b, name='Combo B', price='20.00')

        self.client.force_authenticate(self.manager_a1)
        response = self.client.get('/api/pricing/bundles/')
        names = {row['name'] for row in response.data['results']}
        self.assertEqual(names, {'Combo A'})

        blocked = self.client.post('/api/pricing/bundles/', {
            'entity': str(self.entity_b.id), 'name': 'Sneaky', 'price': '1.00', 'products': [],
        })
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cashier_cannot_set_a_price(self):
        """Pricing is store_manager/entity_admin territory (Settings in
        NAV_DEFS, appData.js) — a cashier's token is refused outright."""
        cashier = User.objects.create_user(username='cashier_p', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=cashier, store=self.store_a1, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        response = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity_a.id), 'product': str(self.product.id), 'unit_price': '5.00',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class PromotionApiTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A1')
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Bottle', unit_value=1)
        self.product = Product.objects.create(entity=self.entity, name='Soda 500ml', uom=uom)
        Price.objects.create(entity=self.entity, product=self.product, unit_price='1000.00')
        self.manager = User.objects.create_user(username='manager', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)
        self.cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.cashier, store=self.store, role=Role.CASHIER)

    def promote(self, **extra):
        return self.client.post('/api/pricing/promotions/', {
            'name': 'Weekend offer', 'product': str(self.product.id), 'promo_price': '800',
            'starts_on': str(timezone.localdate()), 'ends_on': str(timezone.localdate() + timedelta(days=2)), **extra},
            format='json')

    def test_manager_sets_a_promotion_and_everyone_sees_it_running(self):
        self.client.force_authenticate(self.manager)
        response = self.promote()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual((response.data['regular_price'], response.data['is_running']), (Decimal('1000.00'), True))
        self.assertTrue(AuditEvent.objects.filter(action='promotion_changed').exists())
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get('/api/pricing/promotions/', {'running': 'true'}).data['count'], 1)
        self.assertEqual(self.promote().status_code, status.HTTP_403_FORBIDDEN)

    def test_end_before_start_is_refused(self):
        self.client.force_authenticate(self.manager)
        response = self.promote(ends_on=str(timezone.localdate() - timedelta(days=1)))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ends_on', response.data)

    def test_switched_off_promotion_is_not_running(self):
        self.client.force_authenticate(self.manager)
        promotion = self.promote().data
        self.client.patch(f'/api/pricing/promotions/{promotion["id"]}/', {'is_active': False}, format='json')
        self.assertEqual(self.client.get('/api/pricing/promotions/', {'running': 'true'}).data['count'], 0)
