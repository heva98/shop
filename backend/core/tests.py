import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Entity, Role, Store, StoreRole, User


def _tiny_png(name='logo.png'):
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color='red').save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class TenantIsolationTests(APITestCase):
    """Every viewset used to return every entity's rows to any authenticated
    user (see fix commit). These pin the boundary down for the core app."""

    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A')
        self.entity_b = Entity.objects.create(name='Firm B')
        self.store_a = Store.objects.create(entity=self.entity_a, name='A - Main')
        self.store_b = Store.objects.create(entity=self.entity_b, name='B - Main')

        self.cashier_a = User.objects.create_user(username='cashier_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.cashier_a, store=self.store_a, role=Role.CASHIER)

        self.admin_a = User.objects.create_user(username='admin_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.admin_a, store=None, role=Role.ENTITY_ADMIN)

    def test_store_list_excludes_other_entities(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.get('/api/core/stores/')
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(str(self.store_a.id), ids)
        self.assertNotIn(str(self.store_b.id), ids)

    def test_user_list_excludes_other_entities(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.get('/api/core/users/')
        usernames = {row['username'] for row in response.data['results']}
        self.assertIn('cashier_a', usernames)
        self.assertIn('admin_a', usernames)

    def test_entity_admin_sees_only_their_own_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.get('/api/core/entities/')
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {str(self.entity_a.id)})

    def test_user_with_no_entity_sees_nothing(self):
        orphan = User.objects.create_user(username='orphan', password='x')
        self.client.force_authenticate(orphan)
        response = self.client.get('/api/core/stores/')
        self.assertEqual(response.data['results'], [])

    def test_cannot_create_store_under_another_entity(self):
        """get_queryset() filters reads, but create() has no existing row
        to filter — a forged entity id in the body must be rejected here."""
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/stores/', {
            'entity': str(self.entity_b.id), 'name': 'Sneaky Store',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('entity', response.data)

    def test_create_store_defaults_to_own_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/stores/', {'name': 'New Store'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['entity'], self.entity_a.id)

    def test_cannot_create_user_under_another_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/users/', {
            'username': 'sneaky', 'entity': str(self.entity_b.id),
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('entity', response.data)

    def test_cashier_cannot_create_a_store(self):
        """Admin (Stores / Users & roles) is entity_admin territory
        (NAV_DEFS in appData.js) — a cashier's token is refused outright."""
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/core/stores/', {
            'entity': str(self.entity_a.id), 'name': 'New Store',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cashier_cannot_invite_a_user(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/core/users/', {
            'username': 'newbie', 'entity': str(self.entity_a.id),
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_assign_store_role_across_entities(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/store-roles/', {
            'user': str(self.cashier_a.id), 'store': str(self.store_b.id), 'role': 'cashier',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_cashier_cannot_assign_store_roles_at_all(self):
        """Granting roles is entity_admin territory (Admin > Users & roles
        in NAV_DEFS, appData.js) — a cashier's token is refused outright,
        regardless of which store the role would be at."""
        store_a2 = Store.objects.create(entity=self.entity_a, name='A2')
        other_user = User.objects.create_user(username='newbie', password='x', entity=self.entity_a)
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/core/store-roles/', {
            'user': str(other_user.id), 'store': str(store_a2.id), 'role': 'cashier',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_entity_admin_can_assign_store_role_at_any_store_in_their_entity(self):
        store_a2 = Store.objects.create(entity=self.entity_a, name='A2')
        other_user = User.objects.create_user(username='newbie', password='x', entity=self.entity_a)
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/store-roles/', {
            'user': str(other_user.id), 'store': str(store_a2.id), 'role': 'cashier',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_every_role_can_reach_me_regardless_of_write_permissions(self):
        """/me/ is how a frontend login flow learns who it's talking to —
        it must stay reachable even for a role (cashier) with no write
        access anywhere else in core, since it's a GET and UserViewSet's
        role gate (entity_admin, for Admin > Users & roles) only applies
        to unsafe methods."""
        self.client.force_authenticate(self.cashier_a)
        response = self.client.get('/api/core/users/me/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['username'], 'cashier_a')
        self.assertEqual(response.data['store_roles'][0]['role'], 'cashier')

    def test_only_superuser_can_create_entity(self):
        self.client.force_authenticate(self.admin_a)
        response = self.client.post('/api/core/entities/', {'name': 'New Firm'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        superuser = User.objects.create_superuser(username='root', password='x', email='root@example.com')
        self.client.force_authenticate(superuser)
        response = self.client.post('/api/core/entities/', {'name': 'New Firm'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class UserCreationTests(APITestCase):
    """Admin > Users & roles creates staff with credentials and a profile
    (names, gender, date of birth)."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.admin = User.objects.create_user(username='admin_a', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)
        self.payload = {
            'username': 'amina', 'password': 'Str0ng-pass-123',
            'first_name': 'Amina', 'middle_name': 'Said', 'last_name': 'Kassim',
            'gender': 'female', 'date_of_birth': '1995-04-12',
        }

    def test_creates_user_with_profile_and_hashed_password(self):
        response = self.client.post('/api/core/users/', self.payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn('password', response.data)
        user = User.objects.get(username='amina')
        self.assertTrue(user.check_password('Str0ng-pass-123'))
        self.assertEqual(user.entity, self.entity)
        self.assertEqual(
            (user.middle_name, user.gender, str(user.date_of_birth)),
            ('Said', 'female', '1995-04-12'),
        )

    def test_profile_fields_and_password_required_on_create(self):
        response = self.client.post('/api/core/users/', {'username': 'bare'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        for field in ('password', 'first_name', 'last_name', 'gender', 'date_of_birth'):
            self.assertIn(field, response.data)

    def test_middle_name_is_optional(self):
        del self.payload['middle_name']
        response = self.client.post('/api/core/users/', self.payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_weak_password_rejected(self):
        response = self.client.post('/api/core/users/', {**self.payload, 'password': '123'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_future_date_of_birth_rejected(self):
        response = self.client.post('/api/core/users/', {**self.payload, 'date_of_birth': '2999-01-01'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('date_of_birth', response.data)

    def test_patch_without_profile_fields_still_works(self):
        user = User.objects.create_user(username='legacy', password='x', entity=self.entity)
        response = self.client.patch(f'/api/core/users/{user.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_admin_can_edit_profile_and_reset_password(self):
        user = User.objects.create_user(username='legacy2', password='old-Pass-999', entity=self.entity)
        response = self.client.patch(f'/api/core/users/{user.id}/', {
            'first_name': 'Neema', 'password': 'N3w-pass-4567',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        user.refresh_from_db()
        self.assertEqual(user.first_name, 'Neema')
        self.assertTrue(user.check_password('N3w-pass-4567'))

    def test_disabled_user_cannot_authenticate(self):
        user = User.objects.create_user(username='leaver', password='Str0ng-pass-123', entity=self.entity)
        response = self.client.patch(f'/api/core/users/{user.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.client.force_authenticate(None)
        response = self.client.post('/api/auth-token/', {'username': 'leaver', 'password': 'Str0ng-pass-123'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_cannot_disable_themselves(self):
        response = self.client.patch(f'/api/core/users/{self.admin.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_active', response.data)

    def test_cashier_cannot_disable_a_user(self):
        store = Store.objects.create(entity=self.entity, name='A - Main')
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=store, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        response = self.client.patch(f'/api/core/users/{self.admin.id}/', {'is_active': False})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class OwnProfileTests(APITestCase):
    """Any signed-in user edits their own details from the avatar menu."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A - Main')
        self.cashier = User.objects.create_user(username='cashier', password='Old-pass-1234', entity=self.entity)
        StoreRole.objects.create(user=self.cashier, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(self.cashier)

    def test_cashier_can_edit_own_profile(self):
        response = self.client.patch('/api/core/users/me/', {'first_name': 'Juma', 'gender': 'male'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['first_name'], 'Juma')
        self.cashier.refresh_from_db()
        self.assertEqual(self.cashier.gender, 'male')

    def test_cannot_escalate_via_me(self):
        other = Entity.objects.create(name='Firm B')
        self.client.patch('/api/core/users/me/', {'is_active': False, 'entity': str(other.id), 'username': 'boss', 'is_superuser': True})
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.is_active)
        self.assertEqual((self.cashier.entity, self.cashier.username, self.cashier.is_superuser), (self.entity, 'cashier', False))

    def test_password_change_requires_current_password(self):
        response = self.client.patch('/api/core/users/me/', {'current_password': 'wrong', 'new_password': 'N3w-pass-4567'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('current_password', response.data)
        response = self.client.patch('/api/core/users/me/', {'current_password': 'Old-pass-1234', 'new_password': 'N3w-pass-4567'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.cashier.refresh_from_db()
        self.assertTrue(self.cashier.check_password('N3w-pass-4567'))


class EntityProfileTests(APITestCase):
    """Each firm sets its own name/logo — shown in the app header and on
    printed documents (see EntitySerializer, AdminShopProfile.jsx)."""

    @classmethod
    def setUpClass(cls):
        # Logo uploads actually hit disk (ImageField), so point MEDIA_ROOT
        # at a throwaway temp dir instead of littering the real backend/media/.
        cls._media_root = tempfile.mkdtemp(prefix='shop-test-media-')
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.entity = Entity.objects.create(name='Kariakoo Stores')
        self.other_entity = Entity.objects.create(name='Firm B')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)

    def test_entity_admin_can_rename_their_own_shop(self):
        response = self.client.patch(f'/api/core/entities/{self.entity.id}/', {'name': 'Kariakoo Stores Ltd'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.entity.refresh_from_db()
        self.assertEqual(self.entity.name, 'Kariakoo Stores Ltd')

    def test_entity_admin_can_upload_a_logo(self):
        response = self.client.patch(
            f'/api/core/entities/{self.entity.id}/', {'logo': _tiny_png()}, format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.entity.refresh_from_db()
        self.assertTrue(self.entity.logo)

    def test_oversized_logo_rejected(self):
        # A real PNG (so it passes Pillow's own validation) padded past the
        # size cap with trailing bytes after the IEND chunk, which PNG
        # decoders ignore.
        png_bytes = io.BytesIO()
        Image.new('RGB', (4, 4), color='blue').save(png_bytes, format='PNG')
        padded = png_bytes.getvalue() + b'0' * (2 * 1024 * 1024 + 1)
        oversized = SimpleUploadedFile('big.png', padded, content_type='image/png')
        response = self.client.patch(f'/api/core/entities/{self.entity.id}/', {'logo': oversized}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('logo', response.data)

    def test_cannot_edit_another_firms_shop_profile(self):
        response = self.client.patch(f'/api/core/entities/{self.other_entity.id}/', {'name': 'Hijacked'})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admin_cannot_rename_the_shop(self):
        store = Store.objects.create(entity=self.entity, name='Main')
        cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=store, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        response = self.client.patch(f'/api/core/entities/{self.entity.id}/', {'name': 'Renamed by cashier'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StoreRemovalTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm')
        self.main = Store.objects.create(entity=self.entity, name='Main')
        self.branch = Store.objects.create(entity=self.entity, name='Branch')
        self.entity.main_store = self.main
        self.entity.save()

        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)

    def test_admin_can_remove_a_store_without_history(self):
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.branch, role=Role.CASHIER)

        response = self.client.delete(f'/api/core/stores/{self.branch.id}/')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Store.objects.filter(pk=self.branch.pk).exists())
        self.assertFalse(StoreRole.objects.filter(user=cashier).exists())

    def test_cannot_remove_the_main_store(self):
        response = self.client.delete(f'/api/core/stores/{self.main.id}/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Store.objects.filter(pk=self.main.pk).exists())

    def test_store_with_history_is_refused_with_a_400(self):
        from enquiry.models import Transfer
        Transfer.objects.create(from_store=self.main, to_store=self.branch, mode=Transfer.Mode.HUB)

        response = self.client.delete(f'/api/core/stores/{self.branch.id}/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Deactivate', response.data['detail'])
        self.assertTrue(Store.objects.filter(pk=self.branch.pk).exists())

    def test_cashier_cannot_remove_a_store(self):
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.branch, role=Role.CASHIER)
        self.client.force_authenticate(cashier)

        response = self.client.delete(f'/api/core/stores/{self.branch.id}/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Store.objects.filter(pk=self.branch.pk).exists())

    def test_cannot_remove_another_entitys_store(self):
        other = Entity.objects.create(name='Other')
        foreign = Store.objects.create(entity=other, name='Foreign')

        response = self.client.delete(f'/api/core/stores/{foreign.id}/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(Store.objects.filter(pk=foreign.pk).exists())


class SingleStoreModeTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Mama Neema Duka')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)

    def _go_single(self):
        response = self.client.patch(f'/api/core/entities/{self.entity.id}/', {'store_mode': 'single'})
        # force_authenticate keeps reusing admin.entity (this same object)
        # across requests; a real request would load it fresh.
        self.entity.refresh_from_db()
        return response

    def test_switching_to_single_creates_the_store(self):
        response = self._go_single()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(list(self.entity.stores.values_list('name', flat=True)), ['Mama Neema Duka'])

    def test_switching_to_single_reuses_an_existing_store(self):
        store = Store.objects.create(entity=self.entity, name='Nyegezi')

        self._go_single()

        self.assertEqual(list(self.entity.stores.all()), [store])

    def test_cannot_switch_to_single_with_several_active_stores(self):
        for name in ('One', 'Two'):
            Store.objects.create(entity=self.entity, name=name)

        response = self._go_single()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store_mode', response.data)

    def test_staff_role_without_store_goes_to_the_single_store(self):
        self._go_single()
        cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)

        response = self.client.post('/api/core/store-roles/', {'user': cashier.id, 'role': 'cashier'})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(response.data['store']), str(self.entity.stores.get().id))

    def test_cannot_add_a_second_store(self):
        self._go_single()

        response = self.client.post('/api/core/stores/', {'name': 'Branch'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.entity.stores.count(), 1)

    def test_cannot_deactivate_or_remove_the_only_store(self):
        self._go_single()
        store = self.entity.stores.get()

        deactivate = self.client.patch(f'/api/core/stores/{store.id}/', {'is_active': False})
        remove = self.client.delete(f'/api/core/stores/{store.id}/')

        self.assertEqual(deactivate.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(remove.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Store.objects.filter(pk=store.pk, is_active=True).exists())

    def test_multi_store_firm_still_adds_stores(self):
        response = self.client.post('/api/core/stores/', {'name': 'Branch'})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
