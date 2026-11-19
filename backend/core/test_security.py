"""Regression tests for the security audit of 2026-11-19. Each class is one
finding; a test failing here means that hole is open again.

H1  the till's manager approval was a password-guessing box with no limit
H2  an offline sale could break the price, discount and credit limits
    without anyone being told
H3  a server that forgot DEBUG=False handed out password-reset codes
M1  sign-in lockouts: by username only (anyone could lock an owner out),
    and nothing against one password tried on many accounts
M6  parallel code guesses could get past PHONE_CODE_ATTEMPTS
and the owner alerts that make H1/H2/M1 visible (audit.alerts)."""

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.db.models.query import QuerySet
from django.test import override_settings
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.test import APITestCase

from audit import alerts
from audit.models import AuditEvent, SecurityAlert
from credit.models import Customer
from pos.tests import PosTestBase

from .models import Entity, PhoneCode, Role, Store, StoreRole, User
from .phone_codes import check_code, send_code

Action = AuditEvent.Action


class FakeSms:
    """An SMS gateway that sends (so alerts go out) into a list."""
    sends = True
    sent = []

    def default_sender_id(self):
        return 'SHOPPY'

    def send_one(self, phone, body, sender):
        FakeSms.sent.append((phone, body))
        return SimpleNamespace(ok=True, error='')


def fake_sms_gateway():
    return FakeSms()


# ── H1: manager approval at the till ─────────────────────────────────────

@override_settings(LOGIN_LOCKOUT_ATTEMPTS=3)
class ManagerApprovalGuessingTests(PosTestBase):
    def setUp(self):
        super().setUp()
        self.sale = self.new_sale(qty='1')
        self.open_shift()
        self.complete(self.sale['id'])
        self.url = f'/api/pos/sales/{self.sale["id"]}/void/'

    def approve(self, password):
        return self.client.post(self.url, {'reason': 'Wrong item', 'approver_username': 'manager',
                                           'approver_password': password})

    def test_wrong_manager_passwords_lock_the_manager_like_sign_in(self):
        for _ in range(3):
            self.assertEqual(self.approve('guess').status_code, status.HTTP_403_FORBIDDEN)
        locked = self.approve('secret-pw')
        self.assertEqual(locked.status_code, status.HTTP_429_TOO_MANY_REQUESTS, 'even the right password is refused')
        self.client.force_authenticate(None)
        sign_in = self.client.post('/api/auth-token/', {'username': 'manager', 'password': 'secret-pw'})
        self.assertEqual(sign_in.status_code, status.HTTP_429_TOO_MANY_REQUESTS, 'one limit for both doors')

    def test_each_wrong_approval_is_logged_with_who_tried(self):
        self.approve('guess')
        event = AuditEvent.objects.get(action=Action.LOGIN_FAILED)
        self.assertEqual((event.username, event.user), ('manager', self.cashier))
        self.assertIn('manager approval', event.summary)

    def test_wrong_sign_ins_count_toward_the_till_limit(self):
        self.client.force_authenticate(None)
        for _ in range(3):
            self.client.post('/api/auth-token/', {'username': 'manager', 'password': 'guess'})
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.approve('secret-pw').status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_the_right_password_still_approves(self):
        self.assertEqual(self.approve('secret-pw').status_code, status.HTTP_200_OK)
        self.assertFalse(AuditEvent.objects.filter(action=Action.LOGIN_FAILED).exists())


# ── H2: offline sales over a limit ───────────────────────────────────────

class OfflineSaleLimitTests(PosTestBase):
    def setUp(self):
        super().setUp()
        self.shift_id = self.open_shift()

    def offline_sale(self, **overrides):
        payload = {
            'id': str(uuid.uuid4()), 'store': str(self.store.id), 'shift': self.shift_id,
            'items': [{'product': str(self.product.id), 'qty': '3', 'unit_price': '1180'}],
            'payment_method': str(self.cash.id), 'amount_tendered': '5000',
            'completed_at': timezone.now().isoformat(), **overrides,
        }
        response = self.client.post('/api/pos/sales/record/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response

    def reasons(self):
        return sorted(e.data['reason'] for e in AuditEvent.objects.filter(action=Action.OFFLINE_SALE_LIMIT))

    def test_a_sale_within_every_limit_raises_nothing(self):
        self.offline_sale()
        self.assertEqual(self.reasons(), [])

    def test_credit_over_the_customers_limit_is_kept_and_flagged(self):
        customer = Customer.objects.create(entity=self.entity, name='Mama Neema', credit_limit=Decimal('1000'))
        self.offline_sale(customer=str(customer.id), credit_amount='3540', amount_tendered='0')
        self.assertEqual(customer.balance(), Decimal('3540'), 'the sale is kept')
        self.assertEqual(self.reasons(), ['credit_limit'])

    def test_a_date_outside_the_shift_or_long_ago_is_flagged(self):
        self.offline_sale(completed_at='2026-01-02T08:00:00Z')
        self.assertEqual(self.reasons(), ['outside_shift', 'too_old'])

    def test_an_unapproved_discount_over_the_limit_is_flagged(self):
        self.offline_sale(discount='1000')  # 3540, limit 10%
        event = AuditEvent.objects.get(action=Action.DISCOUNT_GIVEN)
        self.assertTrue(event.data['unapproved'])

    def test_a_price_of_nothing_is_kept_and_flagged(self):
        self.offline_sale(items=[{'product': str(self.product.id), 'qty': '3', 'unit_price': '0'}], amount_tendered='0')
        self.assertTrue(AuditEvent.objects.filter(action=Action.OFFLINE_SALE_PRICE).exists())

    def test_a_strict_sale_is_still_refused_over_a_limit(self):
        response = self.client.post('/api/pos/sales/record/', {
            'id': str(uuid.uuid4()), 'store': str(self.store.id), 'strict': True,
            'items': [{'product': str(self.product.id), 'qty': '3', 'unit_price': '1180'}],
            'payment_method': str(self.cash.id), 'amount_tendered': '5000', 'discount': '1000',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ── H3: SMS codes on a server that sends no SMS ──────────────────────────

class SmsCodeExposureTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='0712345678', password='x', phone='255712345678')

    def ask(self):
        return self.client.post('/api/password-reset/code/', {'username': '0712345678'}, format='json')

    @override_settings(SMS_BACKEND='console', DEBUG=True, SHOW_SMS_CODES=False)
    def test_debug_alone_does_not_hand_out_codes(self):
        response = self.ask()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn('debug_code', response.data)
        self.assertFalse(PhoneCode.objects.exists())

    @override_settings(SMS_BACKEND='console', DEBUG=False, SHOW_SMS_CODES=True)
    def test_show_codes_needs_debug_too(self):
        response = self.ask()
        self.assertNotIn('debug_code', response.data)

    @override_settings(SMS_BACKEND='console', DEBUG=True, SHOW_SMS_CODES=True)
    def test_a_development_server_can_show_them(self):
        self.assertIn('debug_code', self.ask().data)


# ── M1: sign-in lockouts and the per-address ceiling ─────────────────────

@override_settings(LOGIN_LOCKOUT_ATTEMPTS=3, LOGIN_LOCKOUT_GLOBAL_ATTEMPTS=6, LOGIN_IP_LOCKOUT_ATTEMPTS=5)
class SignInLockoutTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.owner = User.objects.create_user(username='0712345678', password='Right-pass-1', entity=self.entity)

    def login(self, password, username='0712345678', ip='10.0.0.1', **headers):
        return self.client.post('/api/auth-token/', {'username': username, 'password': password},
                                HTTP_X_REAL_IP=ip, **headers)

    def test_a_stranger_cannot_lock_the_owner_out_from_elsewhere(self):
        for _ in range(3):
            self.login('guess', ip='10.9.9.9')
        self.assertEqual(self.login('Right-pass-1', ip='10.9.9.9').status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(self.login('Right-pass-1', ip='10.0.0.1').status_code, status.HTTP_200_OK,
                         "the owner's own phone still signs in")

    def test_guessing_from_many_addresses_locks_the_username_everywhere(self):
        for i in range(6):
            self.login('guess', ip=f'10.1.0.{i}')
        self.assertEqual(self.login('Right-pass-1', ip='10.0.0.1').status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_one_password_tried_on_many_accounts_blocks_the_address(self):
        for i in range(5):
            self.login('Password1', username=f'07000000{i:02d}', ip='10.6.6.6')
        self.assertEqual(self.login('Right-pass-1', ip='10.6.6.6').status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        blocked = AuditEvent.objects.get(action=Action.LOGIN_LOCKED, data__scope='ip', data__reached=True)
        self.assertEqual(blocked.ip_address, '10.6.6.6')

    def test_a_forged_forwarded_for_header_changes_nothing(self):
        for i in range(3):
            self.login('guess', HTTP_X_FORWARDED_FOR=f'1.2.3.{i}')
        self.assertEqual(self.login('Right-pass-1', HTTP_X_FORWARDED_FOR='9.9.9.9').status_code,
                         status.HTTP_429_TOO_MANY_REQUESTS)

    def test_reaching_the_limit_is_logged_once_for_the_shop(self):
        for _ in range(4):
            self.login('guess')
        reached = AuditEvent.objects.filter(action=Action.LOGIN_LOCKED, data__reached=True)
        self.assertEqual([(e.data['scope'], e.entity) for e in reached], [('user', self.entity)])


class AuthThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(AUTH_THROTTLE_RATE='2/min')
    def test_public_auth_endpoints_are_rate_limited_per_address(self):
        for _ in range(2):
            self.client.post('/api/auth-token/', {'username': 'x', 'password': 'y'}, HTTP_X_REAL_IP='10.0.0.5')
        third = self.client.post('/api/auth-token/', {'username': 'x', 'password': 'y'}, HTTP_X_REAL_IP='10.0.0.5')
        self.assertEqual(third.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        other = self.client.post('/api/auth-token/', {'username': 'x', 'password': 'y'}, HTTP_X_REAL_IP='10.0.0.6')
        self.assertNotEqual(other.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        reset = self.client.post('/api/password-reset/code/', {'username': 'x'}, HTTP_X_REAL_IP='10.0.0.5')
        self.assertEqual(reset.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


# ── M6: guesses at an SMS code ───────────────────────────────────────────

@override_settings(SMS_BACKEND='console', DEBUG=True, SHOW_SMS_CODES=True, PHONE_CODE_ATTEMPTS=5)
@mock.patch('core.phone_codes._new_code', return_value='123456')
class PhoneCodeGuessTests(APITestCase):
    PHONE = '255712345678'

    def test_a_guess_that_read_a_stale_count_is_still_refused(self, _code):
        # Five guesses already counted, but this request read the code
        # before they landed (as parallel requests do).
        send_code(self.PHONE, PhoneCode.Purpose.SIGNUP)
        stale = PhoneCode.objects.get()
        PhoneCode.objects.update(attempts=5)
        with mock.patch.object(QuerySet, 'first', return_value=stale):
            with self.assertRaisesMessage(serializers.ValidationError, 'Too many wrong codes'):
                check_code(self.PHONE, PhoneCode.Purpose.SIGNUP, '123456')
        self.assertEqual(PhoneCode.objects.get().attempts, 5, 'the count never goes backwards')

    def test_a_right_code_works_once(self, _code):
        send_code(self.PHONE, PhoneCode.Purpose.SIGNUP)
        stale = PhoneCode.objects.get()
        check_code(self.PHONE, PhoneCode.Purpose.SIGNUP, '123456')
        with mock.patch.object(QuerySet, 'first', return_value=stale):  # a second request, in flight at once
            with self.assertRaisesMessage(serializers.ValidationError, 'expired'):
                check_code(self.PHONE, PhoneCode.Purpose.SIGNUP, '123456')


# ── Owner alerts ─────────────────────────────────────────────────────────

@override_settings(SMS_GATEWAY='core.test_security.fake_sms_gateway', LOGIN_LOCKOUT_ATTEMPTS=3,
                   ADMINS=[('Platform', 'platform@example.com')])
class SecurityAlertTests(PosTestBase):
    def setUp(self):
        super().setUp()
        FakeSms.sent = []
        self.owner = User.objects.create_user(username='owner', password='x', entity=self.entity,
                                              phone='255713000001', email='owner@example.com')
        StoreRole.objects.create(user=self.owner, store=None, role=Role.ENTITY_ADMIN)

    def texts(self):
        return [body for phone, body in FakeSms.sent if phone == '+255713000001']

    def test_an_offline_sale_at_a_changed_price_reaches_the_owner_once(self):
        self.open_shift()
        self.client.post('/api/pos/sales/record/', {
            'id': str(uuid.uuid4()), 'store': str(self.store.id),
            'items': [{'product': str(self.product.id), 'qty': '3', 'unit_price': '0'}],
            'payment_method': str(self.cash.id), 'amount_tendered': '0',
        }, format='json')
        alerts.run()
        alerts.run()
        self.assertEqual(len(self.texts()), 1)
        self.assertIn('Firm A', self.texts()[0])
        self.assertIn('old prices', self.texts()[0])
        self.assertEqual(len([m for m in mail.outbox if m.to == ['owner@example.com']]), 1)

    def test_a_locked_account_reaches_the_owner(self):
        self.client.force_authenticate(None)
        for _ in range(3):
            self.client.post('/api/auth-token/', {'username': 'manager', 'password': 'guess'})
        alerts.run()
        self.assertEqual(len(self.texts()), 1)
        self.assertIn('manager', self.texts()[0])

    def test_a_new_owner_is_announced_to_the_others_not_to_themselves(self):
        self.client.force_authenticate(User.objects.create_superuser(username='platform', password='x'))
        response = self.client.post(f'/api/platform/shops/{self.entity.id}/owners/', {
            'username': 'newowner', 'password': 'Strong-pass-77', 'first_name': 'New', 'last_name': 'Owner',
            'phone': '0713000002',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        alerts.run()
        self.assertEqual(len(self.texts()), 1)
        self.assertIn('newowner', self.texts()[0])
        self.assertFalse([b for p, b in FakeSms.sent if p == '+255713000002'])

    def test_a_blocked_address_goes_to_the_platform_admins(self):
        self.client.force_authenticate(None)
        with override_settings(LOGIN_IP_LOCKOUT_ATTEMPTS=3):
            for i in range(3):
                self.client.post('/api/auth-token/', {'username': f'nobody{i}', 'password': 'Password1'},
                                 HTTP_X_REAL_IP='10.6.6.6')
        alerts.run()
        self.assertTrue(any('10.6.6.6' in m.body for m in mail.outbox if m.to == ['platform@example.com']))
        self.assertEqual(self.texts(), [], "no shop's owner is texted about it")

    def test_other_shops_owners_hear_nothing(self):
        other = Entity.objects.create(name='Firm B')
        Store.objects.create(entity=other, name='B')
        stranger = User.objects.create_user(username='ownerb', password='x', entity=other, phone='255713000009')
        StoreRole.objects.create(user=stranger, store=None, role=Role.ENTITY_ADMIN)
        self.test_a_locked_account_reaches_the_owner()
        self.assertFalse([b for p, b in FakeSms.sent if p == '+255713000009'])
        self.assertTrue(SecurityAlert.objects.exists())


# ── L3: .xlsx that unpacks to far more than was uploaded ─────────────────

class XlsxBombTests(APITestCase):
    def test_a_part_too_large_once_unpacked_is_refused_before_reading(self):
        import io
        import zipfile

        from imports.parsing import ImportFileError, read_rows

        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('xl/workbook.xml', '<x/>' + ' ' * 5000)
        upload = io.BytesIO(data.getvalue())
        upload.name = 'products.xlsx'
        with mock.patch('imports.parsing.MAX_XLSX_PART_BYTES', 1000):
            with self.assertRaisesMessage(ImportFileError, 'too large once unpacked'):
                read_rows(upload)


# ── M2: the platform administrator's sign-in ─────────────────────────────

class PlatformAdminSignInTests(APITestCase):
    PASSWORD = 'Platform-pass-1'

    def setUp(self):
        self.admin = User.objects.create_superuser(username='platform', password=self.PASSWORD)

    @override_settings(SUPERUSER_TOKEN_TTL_HOURS=4, TOKEN_TTL_HOURS=14)
    def test_administrator_sessions_are_shorter(self):
        from datetime import timedelta

        from rest_framework.authtoken.models import Token
        token = self.client.post('/api/auth-token/', {'username': 'platform', 'password': self.PASSWORD}).data['token']
        Token.objects.filter(key=token).update(created=timezone.now() - timedelta(hours=5))
        response = self.client.get('/api/core/users/me/', HTTP_AUTHORIZATION=f'Token {token}')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def admin_login(self, password=None):
        return self.client.post('/admin/login/?next=/admin/', {'username': 'platform', 'password': password or self.PASSWORD})

    def test_the_admin_site_signs_in_with_the_right_password(self):
        self.assertEqual(self.admin_login().status_code, 302)
        self.assertEqual(self.client.get('/admin/').status_code, 200)

    @override_settings(LOGIN_LOCKOUT_ATTEMPTS=3)
    def test_wrong_passwords_at_the_admin_site_lock_it(self):
        for _ in range(3):
            self.admin_login(password='guess')
        self.assertEqual(AuditEvent.objects.filter(action=Action.LOGIN_FAILED, username='platform').count(), 3)
        self.admin_login()
        self.assertNotEqual(self.client.get('/admin/').status_code, 200, 'the right password is refused while locked')


# ── M3: what a stolen session can do ─────────────────────────────────────

class OwnAccountTests(APITestCase):
    PASSWORD = 'Old-pass-123'

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.user = User.objects.create_user(username='juma', password=self.PASSWORD, entity=self.entity,
                                             phone='255712000001', email='juma@example.com')
        self.token = self.client.post('/api/auth-token/', {'username': 'juma', 'password': self.PASSWORD}).data['token']

    def patch_me(self, token=None, **data):
        return self.client.patch('/api/core/users/me/', data, format='json',
                                 HTTP_AUTHORIZATION=f'Token {token or self.token}')

    def test_a_new_mobile_number_needs_the_current_password(self):
        refused = self.patch_me(phone='0713999999')
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('current_password', refused.data)
        wrong = self.patch_me(phone='0713999999', current_password='wrong')
        self.assertEqual(wrong.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(AuditEvent.objects.filter(action=Action.LOGIN_FAILED, username='juma').exists())
        right = self.patch_me(phone='0713999999', current_password=self.PASSWORD)
        self.assertEqual(right.status_code, status.HTTP_200_OK, right.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, '255713999999')

    def test_a_new_email_needs_it_too(self):
        self.assertEqual(self.patch_me(email='thief@example.com').status_code, status.HTTP_400_BAD_REQUEST)

    def test_other_details_and_an_unchanged_number_need_no_password(self):
        response = self.patch_me(first_name='Juma', phone='0712 000 001', email='juma@example.com')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    @override_settings(LOGIN_LOCKOUT_ATTEMPTS=3)
    def test_guessing_the_current_password_locks_the_account(self):
        for _ in range(3):
            self.patch_me(phone='0713999999', current_password='guess')
        response = self.patch_me(phone='0713999999', current_password=self.PASSWORD)
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_a_new_password_keeps_this_session_only(self):
        # A token is one per user and each sign-in replaces it, so the other
        # session can only be a cookie one (the admin site) alongside it.
        from rest_framework.authtoken.models import Token
        response = self.patch_me(current_password=self.PASSWORD, new_password='New-pass-456!')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(Token.objects.filter(key=self.token).exists(), 'the session that changed it carries on')
        self.user.refresh_from_db()  # the new password, or the session is refused
        self.client.force_login(self.user)
        response = self.client.patch('/api/core/users/me/', {'current_password': 'New-pass-456!',
                                                             'new_password': 'Newer-pass-789!'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(Token.objects.filter(key=self.token).exists(), "the app's session elsewhere ends")

    def test_signing_out_ends_the_session_on_the_server(self):
        response = self.client.post('/api/auth-token/logout/', HTTP_AUTHORIZATION=f'Token {self.token}')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        after = self.client.get('/api/core/users/me/', HTTP_AUTHORIZATION=f'Token {self.token}')
        self.assertEqual(after.status_code, status.HTTP_401_UNAUTHORIZED)


# ── M4: staff details ────────────────────────────────────────────────────

class StaffDetailsTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A')
        self.owner = self._user('owner', None, Role.ENTITY_ADMIN)
        self.manager = self._user('manager', self.store, Role.STORE_MANAGER)
        self.cashier = self._user('cashier', self.store, Role.CASHIER)

    def _user(self, username, store, role):
        user = User.objects.create_user(username=username, password='x', entity=self.entity, phone='255712000009')
        StoreRole.objects.create(user=user, store=store, role=role)
        return user

    def test_only_the_owner_reads_staff_details(self):
        for user in (self.cashier, self.manager):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get('/api/core/users/').status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self.client.get(f'/api/core/users/{self.owner.id}/').status_code,
                             status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.owner)
        self.assertEqual(len(self.client.get('/api/core/users/').data['results']), 3)

    def test_everyone_still_reads_their_own(self):
        self.client.force_authenticate(self.cashier)
        response = self.client.get('/api/core/users/me/')
        self.assertEqual((response.status_code, response.data['username']), (status.HTTP_200_OK, 'cashier'))
