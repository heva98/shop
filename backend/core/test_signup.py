from unittest import mock

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from catalog.models import Product, UnitOfMeasure

from .models import Entity, PhoneCode, Role, Store, StoreRole, User

SHOP = {'name': 'Neema General Store', 'business_type': 'general', 'country': 'TZ', 'region': 'Dar Es Salaam Region',
        'council': 'Kinondoni Municipal Council', 'address': 'Sinza, near the market'}
FORM = {'phone': '0712 345 678', 'first_name': 'Neema', 'last_name': 'Mushi', 'password': 'Duka-Yangu-2026', 'shop': SHOP}


@override_settings(SMS_BACKEND='console', DEBUG=True, SHOW_SMS_CODES=True)
@mock.patch('core.phone_codes._new_code', return_value='123456')
class SignupTests(APITestCase):
    def signup(self, **overrides):
        return self.client.post('/api/signup/', {**FORM, 'code': '123456', **overrides}, format='json')

    def test_owner_signs_up_and_is_signed_in(self, _code):
        response = self.client.post('/api/signup/code/', {'phone': '0712 345 678'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['sent_to'], '0712 ••• 678')

        response = self.signup(starter_products=True)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        entity = Entity.objects.get(name='Neema General Store')
        self.assertTrue(entity.is_active)
        self.assertEqual(entity.store_mode, 'single')
        store = entity.stores.get()
        owner = User.objects.get(username='0712345678')
        self.assertFalse(owner.must_change_password)
        self.assertTrue(owner.check_password('Duka-Yangu-2026'))
        self.assertEqual(set(owner.store_roles.values_list('store', 'role')),
                         {(None, Role.ENTITY_ADMIN), (store.id, Role.CASHIER), (store.id, Role.STOREKEEPER),
                          (store.id, Role.STORE_MANAGER)})
        self.assertTrue(UnitOfMeasure.objects.filter(entity=entity, name='Kilogram').exists())
        self.assertTrue(Product.objects.filter(entity=entity).exists())
        self.assertTrue(AuditEvent.objects.filter(action=AuditEvent.Action.SHOP_REGISTERED, entity=entity).exists())

        me = self.client.get('/api/core/users/me/', HTTP_AUTHORIZATION=f"Token {response.data['token']}")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        for typed in ('0712345678', '0712 345 678', '+255 712 345 678'):
            login = self.client.post('/api/auth-token/', {'username': typed, 'password': 'Duka-Yangu-2026'})
            self.assertEqual(login.status_code, status.HTTP_200_OK, typed)

    def test_units_without_starter_products(self, _code):
        self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        self.assertEqual(self.signup().status_code, status.HTTP_201_CREATED)
        entity = Entity.objects.get()
        self.assertTrue(UnitOfMeasure.objects.filter(entity=entity).exists())
        self.assertFalse(Product.objects.filter(entity=entity).exists())

    def test_wrong_code_is_refused_and_counted(self, _code):
        self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        response = self.signup(code='000000')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('code', response.data)
        self.assertFalse(Entity.objects.exists())
        self.assertEqual(PhoneCode.objects.get().attempts, 1)

    @override_settings(PHONE_CODE_ATTEMPTS=2)
    def test_too_many_guesses_burn_the_code(self, _code):
        self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        self.signup(code='000000')
        self.signup(code='000001')
        self.assertEqual(self.signup().status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Entity.objects.exists())

    def test_form_errors_cost_no_guess(self, _code):
        self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        response = self.signup(password='123', code='000000')
        self.assertIn('password', response.data)
        self.assertEqual(PhoneCode.objects.get().attempts, 0)
        response = self.signup(shop={**SHOP, 'council': 'Arusha City Council'})
        self.assertIn('council', response.data)

    def test_number_already_registered(self, _code):
        User.objects.create_user(username='0712345678', password='x')
        response = self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phone', response.data)

    def test_landlines_and_bad_numbers(self, _code):
        self.assertIn('phone', self.client.post('/api/signup/code/', {'phone': '0222 123 456'}, format='json').data)
        self.assertIn('phone', self.client.post('/api/signup/code/', {'phone': '12'}, format='json').data)

    @override_settings(PHONE_CODE_PER_PHONE_HOURLY=2)
    def test_codes_are_rate_limited(self, _code):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json').status_code, 200)
        self.assertEqual(self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json').status_code, 400)

    @override_settings(SIGNUP_OPEN=False)
    def test_signup_can_be_closed(self, _code):
        response = self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_regions_load_before_sign_in(self, _code):
        self.assertEqual(self.client.get('/api/core/locations/').status_code, status.HTTP_200_OK)

    def test_regions_load_with_a_stale_token(self, _code):
        # A token left in the browser from an expired session must not
        # empty the sign-up page's dropdowns.
        response = self.client.get('/api/core/locations/', HTTP_AUTHORIZATION='Token no-such-token')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['countries'])


@override_settings(SMS_BACKEND='console', DEBUG=True, SHOW_SMS_CODES=True)
@mock.patch('core.phone_codes._new_code', return_value='654321')
class PasswordResetTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Duka')
        self.store = Store.objects.create(entity=self.entity, name='Duka')
        self.user = User.objects.create_user(username='asha', password='Old-pass-2026', entity=self.entity,
                                             phone='255712345678', must_change_password=True)
        StoreRole.objects.create(user=self.user, store=self.store, role=Role.CASHIER)

    def reset(self, **overrides):
        return self.client.post('/api/password-reset/', {'username': 'asha', 'code': '654321',
                                                         'new_password': 'New-pass-2026', **overrides}, format='json')

    def test_reset_with_sms_code(self, _code):
        response = self.client.post('/api/password-reset/code/', {'username': 'Asha'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['sent_to'], '0712 ••• 678')
        response = self.reset()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('New-pass-2026'))
        self.assertFalse(self.user.must_change_password)
        self.assertIn('token', response.data)
        self.assertEqual(self.reset().status_code, status.HTTP_400_BAD_REQUEST)  # the code is used up

    def test_wrong_code_keeps_the_password(self, _code):
        self.client.post('/api/password-reset/code/', {'username': 'asha'}, format='json')
        self.assertEqual(self.reset(code='111111').status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Old-pass-2026'))

    def test_a_signup_code_cannot_reset_a_password(self, _code):
        User.objects.filter(pk=self.user.pk).update(phone='255712345679')
        self.client.post('/api/signup/code/', {'phone': '0712345679'}, format='json')
        self.assertEqual(self.reset().status_code, status.HTTP_400_BAD_REQUEST)

    def test_account_without_phone(self, _code):
        User.objects.filter(pk=self.user.pk).update(phone='')
        response = self.client.post('/api/password-reset/code/', {'username': 'asha'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('username', response.data)

    def test_owner_may_type_their_number(self, _code):
        User.objects.create_user(username='0713000000', password='x', entity=self.entity, phone='255713000000')
        response = self.client.post('/api/password-reset/code/', {'username': '0713 000 000'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['username'], '0713000000')

    def test_superusers_reset_on_the_server(self, _code):
        User.objects.create_superuser(username='platform', password='x', phone='255713000000')
        response = self.client.post('/api/password-reset/code/', {'username': 'platform'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(SMS_BACKEND='noop', DEBUG=False)
class NoSmsConfiguredTests(APITestCase):
    def test_codes_are_refused_rather_than_lost(self):
        response = self.client.post('/api/signup/code/', {'phone': '0712345678'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('detail', response.data)
        self.assertFalse(PhoneCode.objects.exists())
