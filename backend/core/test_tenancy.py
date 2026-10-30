"""Cross-shop boundaries found in the multi-shop audit: nothing one shop's
owner or staff do may change, or reach into, another shop."""

from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from payments.models import EntityPaymentMethod, PaymentMethod
from receiving.models import ReceivingInvoice, Supplier

from .models import Entity, ModuleRegistry, Role, Store, StoreRole, User


class TwoShops(APITestCase):
    def setUp(self):
        self.shop_a = Entity.objects.create(name='Shop A')
        self.shop_b = Entity.objects.create(name='Shop B')
        self.store_a = Store.objects.create(entity=self.shop_a, name='A')
        self.store_b = Store.objects.create(entity=self.shop_b, name='B')
        self.owner_a = self._user('owner_a', self.shop_a, None, Role.ENTITY_ADMIN)
        self.owner_b = self._user('owner_b', self.shop_b, None, Role.ENTITY_ADMIN)
        self.seller_a = self._user('seller_a', self.shop_a, self.store_a, Role.CASHIER)
        uom_b = UnitOfMeasure.objects.create(entity=self.shop_b, name='Piece', unit_value=1)
        self.product_b = Product.objects.create(entity=self.shop_b, name='Soap B', uom=uom_b)
        self.platform = User.objects.create_superuser(username='platform', password='x')

    @staticmethod
    def _user(username, entity, store, role):
        user = User.objects.create_user(username=username, password='x', entity=entity)
        StoreRole.objects.create(user=user, store=store, role=role)
        return user


class PaymentMethodPerShopTests(TwoShops):
    def setUp(self):
        super().setUp()
        self.mobile, _ = PaymentMethod.objects.get_or_create(
            implementation=PaymentMethod.Implementation.MOBILE_MONEY,
            defaults={'name': 'Mobile money', 'is_active': True})

    def _toggle(self, user, on):
        self.client.force_authenticate(user)
        return self.client.patch(f'/api/payments/payment-methods/{self.mobile.id}/', {'is_active': on})

    def test_one_shop_switching_a_method_off_leaves_the_other_shop_alone(self):
        self.assertEqual(self._toggle(self.owner_a, False).status_code, status.HTTP_200_OK)
        self.mobile.refresh_from_db()
        self.assertTrue(self.mobile.is_active)
        self.assertFalse(self.mobile.is_active_for(self.shop_a))
        self.assertTrue(self.mobile.is_active_for(self.shop_b))
        self.assertNotIn(self.mobile, PaymentMethod.active_for(self.shop_a))
        self.assertIn(self.mobile, PaymentMethod.active_for(self.shop_b))

    def test_list_shows_the_callers_own_switch(self):
        self._toggle(self.owner_a, False)
        self.client.force_authenticate(self.owner_b)
        rows = {r['id']: r for r in self.client.get('/api/payments/payment-methods/').data['results']}
        self.assertTrue(rows[str(self.mobile.id)]['is_active'])
        self.client.force_authenticate(self.owner_a)
        rows = {r['id']: r for r in self.client.get('/api/payments/payment-methods/').data['results']}
        self.assertFalse(rows[str(self.mobile.id)]['is_active'])

    def test_platform_admin_sets_the_default_for_shops_without_their_own_switch(self):
        EntityPaymentMethod.objects.create(entity=self.shop_a, method=self.mobile, is_active=True)
        self.assertEqual(self._toggle(self.platform, False).status_code, status.HTTP_200_OK)
        self.mobile.refresh_from_db()
        self.assertTrue(self.mobile.is_active_for(self.shop_a))
        self.assertFalse(self.mobile.is_active_for(self.shop_b))

    def test_owner_cannot_create_or_delete_methods(self):
        self.client.force_authenticate(self.owner_a)
        self.assertEqual(self.client.delete(f'/api/payments/payment-methods/{self.mobile.id}/').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.post('/api/payments/payment-methods/', {'name': 'X', 'implementation': 'cash'})
                         .status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class ModuleRegistryTests(TwoShops):
    def test_owner_cannot_change_the_shared_module_list(self):
        module = ModuleRegistry.objects.get(key='pos_sale')
        self.client.force_authenticate(self.owner_a)
        self.assertEqual(self.client.delete(f'/api/core/modules/{module.id}/').status_code,
                         status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/core/modules/').status_code, status.HTTP_200_OK)

    def test_platform_admin_can(self):
        self.client.force_authenticate(self.platform)
        response = self.client.post('/api/core/modules/', {'key': 'new_thing', 'name': 'New', 'scope': 'entity'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class ForeignProductTests(TwoShops):
    """Shop A's staff can't write shop B's products into shop A's records."""

    def setUp(self):
        super().setUp()
        self.manager_a = self._user('manager_a', self.shop_a, self.store_a, Role.STORE_MANAGER)
        self.client.force_authenticate(self.manager_a)

    def test_receiving_line(self):
        supplier = Supplier.objects.create(entity=self.shop_a, name='Supplier A')
        draft = ReceivingInvoice.objects.create(store=self.store_a, supplier=supplier, invoice_number='1',
                                                received_date='2026-01-01')
        response = self.client.post('/api/receiving/invoice-lines/', {
            'invoice': str(draft.id), 'product': str(self.product_b.id), 'uom': str(self.product_b.uom_id),
            'order_qty': 1, 'pack_price': 100,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('product', response.data)
        self.assertIn('uom', response.data)

    def test_nested_receiving_lines(self):
        supplier = Supplier.objects.create(entity=self.shop_a, name='Supplier A')
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(self.store_a.id), 'supplier': str(supplier.id), 'invoice_number': '2',
            'received_date': '2026-01-01',
            'lines': [{'product': str(self.product_b.id), 'uom': str(self.product_b.uom_id),
                       'order_qty': 1, 'pack_price': 100}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_store_product(self):
        response = self.client.post('/api/inventory/store-products/', {
            'store': str(self.store_a.id), 'product': str(self.product_b.id), 'reorder_level': 5,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stock_batch(self):
        response = self.client.post('/api/inventory/batches/', {
            'store': str(self.store_a.id), 'product': str(self.product_b.id), 'unit_cost': 10,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class NoShopTests(TwoShops):
    def test_admin_role_without_a_shop_sees_no_analytics(self):
        stray = self._user('stray', None, None, Role.ENTITY_ADMIN)
        self.client.force_authenticate(stray)
        self.assertEqual(self.client.get('/api/analytics/dimensions/').status_code, status.HTTP_403_FORBIDDEN)


class OwnerAndSellerTests(TwoShops):
    """Owners add and manage sellers; owners themselves are the platform
    administrator's to appoint, change and remove."""

    def test_owner_can_give_a_seller_a_store_role(self):
        self.client.force_authenticate(self.owner_a)
        new = User.objects.create_user(username='new_seller', password='x', entity=self.shop_a)
        response = self.client.post('/api/core/store-roles/', {
            'user': new.id, 'store': str(self.store_a.id), 'role': Role.STORE_MANAGER})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_owner_cannot_make_another_owner(self):
        self.client.force_authenticate(self.owner_a)
        response = self.client.post('/api/core/store-roles/', {'user': self.seller_a.id, 'role': Role.ENTITY_ADMIN})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_cannot_remove_an_owner_role(self):
        co_owner = self._user('co_owner', self.shop_a, None, Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.owner_a)
        role = co_owner.store_roles.get()
        self.assertEqual(self.client.delete(f'/api/core/store-roles/{role.id}/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_owner_cannot_reset_another_owners_password(self):
        co_owner = self._user('co_owner', self.shop_a, None, Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.owner_a)
        response = self.client.patch(f'/api/core/users/{co_owner.id}/', {'password': 'Takeover-123!'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.delete(f'/api/core/users/{co_owner.id}/').status_code,
                         status.HTTP_403_FORBIDDEN)

    def test_owner_can_still_manage_a_seller(self):
        self.client.force_authenticate(self.owner_a)
        response = self.client.patch(f'/api/core/users/{self.seller_a.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_owner_cannot_unlink_a_seller_from_the_shop(self):
        self.client.force_authenticate(self.owner_a)
        response = self.client.patch(f'/api/core/users/{self.seller_a.id}/', {'entity': ''})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_owner_cannot_touch_another_shops_seller(self):
        self.client.force_authenticate(self.owner_b)
        response = self.client.patch(f'/api/core/users/{self.seller_a.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
