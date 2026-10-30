from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from .models import Entity, Role, Store, StoreRole, User

OWNER = {'username': 'mama_neema', 'password': 'Duka-Yangu-2026', 'first_name': 'Neema', 'last_name': 'Mushi',
         'phone': '0712 345 678'}
SHOP = {'name': 'Neema General Store', 'business_type': 'general', 'region': 'Dar es Salaam',
        'district': 'Kinondoni', 'address': 'Sinza, near the market', 'store_mode': 'single'}


class RegisterShopTests(APITestCase):
    def setUp(self):
        self.platform = User.objects.create_superuser(username='platform', password='x')
        self.client.force_authenticate(self.platform)

    def register(self, **overrides):
        return self.client.post('/api/platform/shops/', {**SHOP, 'owner': OWNER, **overrides}, format='json')

    def test_creates_shop_store_and_owner_together(self):
        response = self.register()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        entity = Entity.objects.get(name='Neema General Store')
        self.assertEqual(entity.region, 'Dar es Salaam')
        store = entity.stores.get()
        self.assertEqual(store.address, 'Sinza, near the market')
        owner = User.objects.get(username='mama_neema')
        self.assertEqual(owner.entity, entity)
        self.assertEqual(owner.phone, '255712345678')
        self.assertTrue(owner.must_change_password)
        self.assertTrue(owner.check_password(OWNER['password']))
        self.assertTrue(StoreRole.objects.filter(user=owner, store=None, role=Role.ENTITY_ADMIN).exists())
        self.assertEqual([o['username'] for o in response.data['owners']], ['mama_neema'])

    def test_multi_branch_shop_starts_with_one_store(self):
        self.register(store_mode='multi')
        entity = Entity.objects.get(name='Neema General Store')
        self.assertEqual(entity.stores.count(), 1)

    def test_owner_is_required(self):
        response = self.client.post('/api/platform/shops/', SHOP, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Entity.objects.exists())

    def test_bad_owner_leaves_nothing_behind(self):
        User.objects.create_user(username='mama_neema', password='x')
        response = self.register()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('owner', response.data)
        self.assertFalse(Entity.objects.exists())
        self.assertFalse(Store.objects.exists())

    def test_weak_password_refused(self):
        response = self.register(owner={**OWNER, 'password': '123'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_add_a_second_owner(self):
        shop_id = self.register().data['id']
        response = self.client.post(f'/api/platform/shops/{shop_id}/owners/',
                                    {**OWNER, 'username': 'baba_neema', 'first_name': 'Juma'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        listed = self.client.get(f'/api/platform/shops/{shop_id}/').data
        self.assertEqual({o['username'] for o in listed['owners']}, {'mama_neema', 'baba_neema'})

    def test_list_counts(self):
        self.register()
        row = self.client.get('/api/platform/shops/').data['results'][0]
        self.assertEqual((row['store_count'], row['staff_count']), (1, 1))
        self.assertEqual(row['business_type_label'], 'General shop (duka)')

    def test_shops_cannot_be_deleted(self):
        shop_id = self.register().data['id']
        self.assertEqual(self.client.delete(f'/api/platform/shops/{shop_id}/').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)


class PlatformAccessTests(APITestCase):
    def test_shop_owner_cannot_use_the_platform_console(self):
        entity = Entity.objects.create(name='Shop A')
        owner = User.objects.create_user(username='owner', password='x', entity=entity)
        StoreRole.objects.create(user=owner, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(owner)
        self.assertEqual(self.client.get('/api/platform/shops/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.post('/api/platform/shops/', {**SHOP, 'owner': OWNER}, format='json')
                         .status_code, status.HTTP_403_FORBIDDEN)

    def test_owner_cannot_unsuspend_their_own_shop(self):
        entity = Entity.objects.create(name='Shop A')
        owner = User.objects.create_user(username='owner', password='x', entity=entity)
        StoreRole.objects.create(user=owner, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(owner)
        self.client.patch(f'/api/core/entities/{entity.id}/', {'is_active': False})
        entity.refresh_from_db()
        self.assertTrue(entity.is_active)


class SuspendShopTests(APITestCase):
    def setUp(self):
        self.platform = User.objects.create_superuser(username='platform', password='x')
        self.entity = Entity.objects.create(name='Shop A')
        self.seller = User.objects.create_user(username='seller', password='Duka-Yangu-2026', entity=self.entity)

    def suspend(self):
        self.client.force_authenticate(self.platform)
        response = self.client.patch(f'/api/platform/shops/{self.entity.id}/', {'is_active': False})
        self.client.force_authenticate(None)
        return response

    def test_suspended_shop_staff_cannot_sign_in(self):
        self.assertEqual(self.suspend().status_code, status.HTTP_200_OK)
        response = self.client.post('/api/auth-token/', {'username': 'seller', 'password': 'Duka-Yangu-2026'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('suspended', response.data['detail'])

    def test_suspending_ends_open_sessions(self):
        token = Token.objects.create(user=self.seller)
        self.suspend()
        self.assertFalse(Token.objects.filter(pk=token.pk).exists())

    def test_token_of_a_suspended_shop_is_refused(self):
        token = Token.objects.create(user=self.seller)
        Entity.objects.filter(pk=self.entity.pk).update(is_active=False)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        self.assertEqual(self.client.get('/api/core/users/me/').status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reactivated_shop_can_sign_in_again(self):
        self.suspend()
        self.client.force_authenticate(self.platform)
        self.client.patch(f'/api/platform/shops/{self.entity.id}/', {'is_active': True})
        self.client.force_authenticate(None)
        response = self.client.post('/api/auth-token/', {'username': 'seller', 'password': 'Duka-Yangu-2026'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
