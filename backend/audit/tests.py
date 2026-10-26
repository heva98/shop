from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User

from .models import AuditEvent


class SignInTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.user = User.objects.create_user(username='juma', password='Correct-horse-9', entity=self.entity)

    def login(self, password='Correct-horse-9', username='juma'):
        return self.client.post('/api/auth-token/', {'username': username, 'password': password})

    def test_sign_in_issues_a_fresh_token_and_is_logged(self):
        first = self.login().data['token']
        second = self.login().data['token']
        self.assertNotEqual(first, second, 'each sign-in rotates the token')
        self.assertFalse(Token.objects.filter(key=first).exists())
        self.assertEqual(AuditEvent.objects.filter(action='login', username='juma').count(), 2)

    @override_settings(LOGIN_LOCKOUT_ATTEMPTS=3)
    def test_repeated_wrong_passwords_lock_the_username(self):
        for _ in range(3):
            self.assertEqual(self.login('wrong').status_code, status.HTTP_400_BAD_REQUEST)
        locked = self.login()
        self.assertEqual(locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS, 'even the right password is refused')
        self.assertEqual(AuditEvent.objects.filter(action='login_failed').count(), 3)
        self.assertTrue(AuditEvent.objects.filter(action='login_locked').exists())

    @override_settings(LOGIN_LOCKOUT_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=15)
    def test_lockout_wears_off(self):
        for _ in range(3):
            self.login('wrong')
        AuditEvent.objects.update(created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self.login().status_code, status.HTTP_200_OK)

    @override_settings(TOKEN_TTL_HOURS=12)
    def test_tokens_expire(self):
        token = self.login().data['token']
        Token.objects.filter(key=token).update(created=timezone.now() - timedelta(hours=13))
        response = self.client.get('/api/core/users/me/', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('expired', response.data['detail'])


class AdminAccountTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Main')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.staff = User.objects.create_user(username='juma', password='Old-pass-123', entity=self.entity)
        self.staff_token = Token.objects.create(user=self.staff)
        self.client.force_authenticate(self.admin)

    def test_admin_password_reset_signs_out_and_forces_a_change(self):
        response = self.client.patch(f'/api/core/users/{self.staff.id}/', {'password': 'Temp-pass-456'})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.must_change_password)
        self.assertFalse(Token.objects.filter(pk=self.staff_token.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action='password_reset', data__user='juma').exists())

        self.client.force_authenticate(self.staff)
        me = self.client.patch('/api/core/users/me/', {'current_password': 'Temp-pass-456', 'new_password': 'Mine-now-789'})
        self.assertFalse(me.data['must_change_password'])

    def test_disabling_signs_out_and_is_logged(self):
        self.client.patch(f'/api/core/users/{self.staff.id}/', {'is_active': False})
        self.assertFalse(Token.objects.filter(user=self.staff).exists())
        self.assertTrue(AuditEvent.objects.filter(action='user_disabled').exists())

    def test_phone_numbers_are_normalized(self):
        response = self.client.patch(f'/api/core/users/{self.staff.id}/', {'phone': '0712 345 678'})
        self.assertEqual(response.data['phone'], '255712345678')
        bad = self.client.patch(f'/api/core/users/{self.staff.id}/', {'phone': '12'})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)


class AuditTrailTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Main')
        self.other_store = Store.objects.create(entity=self.entity, name='Other')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=self.entity, name='Paracetamol', uom=uom)
        self.client.force_authenticate(self.admin)

    def test_price_changes_record_old_and_new(self):
        created = self.client.post('/api/pricing/prices/', {
            'entity': str(self.entity.id), 'product': str(self.product.id), 'unit_price': '100'})
        self.client.patch(f'/api/pricing/prices/{created.data["id"]}/', {'unit_price': '120'})
        event = AuditEvent.objects.filter(action='price_set').order_by('created_at').last()
        self.assertEqual((event.data['old'], event.data['new']), ('100.00', '120.00'))
        self.assertEqual(event.username, 'admin')

    def test_product_flag_changes_are_logged(self):
        self.client.patch(f'/api/catalog/products/{self.product.id}/', {'tracks_expiry': True})
        event = AuditEvent.objects.get(action='product_updated')
        self.assertEqual(event.data['tracks_expiry'], [False, True])

    def test_store_manager_sees_only_their_stores_events_and_cashier_none(self):
        AuditEvent.objects.create(entity=self.entity, store=self.store, action='sale_voided', summary='here')
        AuditEvent.objects.create(entity=self.entity, store=self.other_store, action='sale_voided', summary='there')
        manager = User.objects.create_user(username='mgr', password='x', entity=self.entity)
        StoreRole.objects.create(user=manager, store=self.store, role=Role.STORE_MANAGER)
        self.client.force_authenticate(manager)
        summaries = [e['summary'] for e in self.client.get('/api/audit/events/').data['results']]
        self.assertEqual(summaries, ['here'])

        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        self.assertEqual(self.client.get('/api/audit/events/').status_code, status.HTTP_403_FORBIDDEN)

    def test_the_log_cannot_be_written_through_the_api(self):
        response = self.client.post('/api/audit/events/', {'action': 'login', 'summary': 'fake'})
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class HealthTests(APITestCase):
    def test_health_is_public_and_ok(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['database'], 'ok')

    def test_missing_backups_fail_the_health_check(self):
        import tempfile
        with tempfile.TemporaryDirectory() as empty, override_settings(BACKUP_DIR=empty):
            response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['backup'], 'none found')

