from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Entity, Role, Store, StoreRole, User

from .models import Category, Product, UnitOfMeasure


class CatalogTenantIsolationTests(APITestCase):
    """Product/Category/UnitOfMeasure used to have no entity at all —
    any authenticated user could read or edit any firm's catalog. These
    pin the boundary down now that catalog is entity-scoped."""

    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A')
        self.entity_b = Entity.objects.create(name='Firm B')
        self.store_a = Store.objects.create(entity=self.entity_a, name='A')

        self.cashier_a = User.objects.create_user(username='cashier_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.cashier_a, store=self.store_a, role=Role.CASHIER)

        self.admin_a = User.objects.create_user(username='admin_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.admin_a, store=None, role=Role.ENTITY_ADMIN)

        self.uom_a = UnitOfMeasure.objects.create(entity=self.entity_a, name='Strip', unit_value=10)
        self.uom_b = UnitOfMeasure.objects.create(entity=self.entity_b, name='Strip', unit_value=10)
        self.generic_a = Category.objects.create(entity=self.entity_a, name='Amoxicillin')
        self.product_a = Product.objects.create(
            entity=self.entity_a, name='Amoxicillin 500mg', uom=self.uom_a,
        )
        self.product_b = Product.objects.create(
            entity=self.entity_b, name='Other firm drug', uom=self.uom_b,
        )

    def test_product_list_excludes_other_entities(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.get('/api/catalog/products/')
        ids = {row['id'] for row in response.data['results']}
        self.assertIn(str(self.product_a.id), ids)
        self.assertNotIn(str(self.product_b.id), ids)

    def test_uom_list_excludes_other_entities(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.get('/api/catalog/units-of-measure/')
        ids = {row['id'] for row in response.data['results']}
        self.assertIn(str(self.uom_a.id), ids)
        self.assertNotIn(str(self.uom_b.id), ids)

    def test_cannot_create_product_under_another_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/catalog/products/', {
            'entity': str(self.entity_b.id), 'name': 'Sneaky', 'uom': str(self.uom_b.id),
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('entity', response.data)

    def test_cannot_create_product_with_a_uom_from_another_entity(self):
        """entity is owned correctly, but the uom it points at belongs to
        a different firm's catalog — must be rejected even though the
        entity field alone passed."""
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/catalog/products/', {
            'entity': str(self.entity_a.id), 'name': 'Mismatched', 'uom': str(self.uom_b.id),
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('uom', response.data)

    def test_can_create_product_within_own_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/catalog/products/', {
            'entity': str(self.entity_a.id), 'name': 'New product',
            'uom': str(self.uom_a.id), 'category': str(self.generic_a.id),
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_cashier_cannot_create_a_product(self):
        """Generic drugs & products is entity_admin territory (Settings
        in NAV_DEFS, appData.js) — a cashier's token is refused outright."""
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/catalog/products/', {
            'entity': str(self.entity_a.id), 'name': 'Nope', 'uom': str(self.uom_a.id),
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class BarcodeTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        Product.objects.create(entity=self.entity, name='Panadol', uom=self.uom, barcode='6001234567890')
        self.client.force_authenticate(self.admin)

    def test_duplicate_barcode_is_refused_within_a_shop(self):
        response = self.client.post('/api/catalog/products/', {
            'entity': str(self.entity.id), 'name': 'Other', 'uom': str(self.uom.id),
            'barcode': ' 6001234567890 ',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('barcode', response.data)

    def test_lookup_by_exact_barcode(self):
        response = self.client.get('/api/catalog/products/', {'barcode': '6001234567890'})
        self.assertEqual([p['name'] for p in response.data['results']], ['Panadol'])
