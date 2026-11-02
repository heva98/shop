import base64
import io
import json
import urllib.error
from datetime import date, time
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, ModuleEnablement, ModuleRegistry, Role, Store, StoreRole, User
from core.phone import is_tz_mobile, normalize_tz_phone
from inventory.models import StockBatch
from payments.models import PaymentMethod
from pos.models import Sale, Shift
from pricing.models import Price

from .models import NotificationLog, SmsBatch, SmsConfiguration, SmsMessage, SmsTemplate
from .sms_backends import BeemBackend, NotifyAfricaBackend
from .sms_jobs import daily_sales_sms_run
from .sms_segments import count_segments
from .sms_service import ensure_templates
from .sms_templates import DAILY_SALES_SUMMARY, MissingPlaceholder, TemplateSyntaxError, check_template, render

# DAILY_SUMMARY_TIME 00:00: the summaries are due whenever the tests run.
NOTIFY = dict(SMS_BACKEND='notify_africa', NOTIFY_AFRICA_BASE_URL='https://api.notify.africa',
              NOTIFY_AFRICA_API_TOKEN='tok', NOTIFY_AFRICA_SENDER_ID='55', SMS_PROVIDER_CHUNK_SLEEP=0,
              DAILY_SUMMARY_TIME='00:00')
BEEM = dict(SMS_BACKEND='beem', BEEM_API_KEY='key', BEEM_SECRET_KEY='secret', BEEM_SENDER_ID='KILIMANI')


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


NOTIFY_OK = {'status': 200, 'message': 'SMS sent', 'data': {'messageId': 'm-1', 'status': 'PROCESSING'}}


def http_error(code, body):
    return urllib.error.HTTPError('u', code, 'x', {}, io.BytesIO(json.dumps(body).encode()))


@override_settings(**NOTIFY)
class NotifyAfricaBackendTests(SimpleTestCase):
    def send(self, **patch):
        with mock.patch('urllib.request.urlopen', **patch) as urlopen:
            return NotifyAfricaBackend().send_one('+255712345678', 'Hello', '55'), urlopen

    def test_sends_the_documented_request(self):
        result, urlopen = self.send(return_value=FakeResponse(NOTIFY_OK))
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://api.notify.africa/api/v1/api/messages/send')
        self.assertEqual(request.get_header('Authorization'), 'Bearer tok')
        self.assertEqual(json.loads(request.data),
                         {'phone_number': '255712345678', 'message': 'Hello', 'sender_id': '55'})
        self.assertTrue(result.ok)
        self.assertEqual(result.provider_message_id, 'm-1')

    def test_failures_are_classified_not_raised(self):
        cases = [
            (dict(side_effect=http_error(401, {'message': 'bad token'})), 'unauthorized'),
            (dict(side_effect=http_error(402, {})), 'insufficient_credit'),
            (dict(side_effect=http_error(400, {'message': 'Insufficient balance'})), 'insufficient_credit'),
            (dict(side_effect=http_error(500, {})), 'http_500'),
            (dict(return_value=FakeResponse({'status': 'failed'})), 'rejected'),
            (dict(return_value=FakeResponse({'success': False})), 'rejected'),
            (dict(side_effect=TimeoutError()), 'timeout'),
            (dict(side_effect=urllib.error.URLError('refused')), 'connection_error'),
        ]
        for patch, error in cases:
            with self.subTest(error=error):
                result, _ = self.send(**patch)
                self.assertFalse(result.ok)
                self.assertEqual(result.error, error)


@override_settings(**BEEM)
class BeemBackendTests(SimpleTestCase):
    def test_sends_the_documented_request(self):
        ok = FakeResponse({'successful': True, 'code': 100, 'valid': 1, 'invalid': 0})
        with mock.patch('urllib.request.urlopen', return_value=ok) as urlopen:
            self.assertTrue(BeemBackend().send_one('+255712345678', 'Hello', 'KILIMANI').ok)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(b'key:secret').decode())
        body = json.loads(request.data)
        self.assertEqual(body['source_addr'], 'KILIMANI')
        self.assertEqual(body['recipients'], [{'recipient_id': 1, 'dest_addr': '255712345678'}])

    def test_a_refusal_is_reported(self):
        bad = FakeResponse({'successful': False, 'code': 102, 'message': 'Insufficient balance'})
        with mock.patch('urllib.request.urlopen', return_value=bad):
            self.assertEqual(BeemBackend().send_one('+255712345678', 'Hello', 'K').error, 'insufficient_credit')


class PhoneTests(SimpleTestCase):
    def test_normalize(self):
        for raw in ('0713123123', '255713123123', '+255 713 123 123', '713123123', '00255713123123'):
            self.assertEqual(normalize_tz_phone(raw), '+255713123123', raw)
        for raw in ('', None, '12345', '+254713123123'):
            self.assertIsNone(normalize_tz_phone(raw), raw)

    def test_only_mobiles(self):
        self.assertTrue(is_tz_mobile('+255613123123'))
        self.assertFalse(is_tz_mobile('+255222123123'))


class SegmentAndTemplateTests(SimpleTestCase):
    def test_segments(self):
        self.assertEqual(count_segments('a' * 160), 1)
        self.assertEqual(count_segments('a' * 161), 2)
        self.assertEqual(count_segments('€' * 80), 1)
        self.assertEqual(count_segments('€' * 81), 2)
        self.assertEqual(count_segments('ŵ' + 'a' * 69), 1)
        self.assertEqual(count_segments('ŵ' + 'a' * 70), 2)

    def test_render_is_strict(self):
        self.assertEqual(render('Hi {store}', {'store': 'Kilimani'}), 'Hi Kilimani')
        for values in ({}, {'store': None}, {'store': '  '}):
            with self.assertRaises(MissingPlaceholder):
                render('Hi {store}', values)

    def test_template_check(self):
        check_template('{store} {sales_total}', DAILY_SALES_SUMMARY)
        for bad in ('{store', '{nope}', '{store.name}'):
            with self.assertRaises(TemplateSyntaxError):
                check_template(bad, DAILY_SALES_SUMMARY)


def fake_send(*_args, **_kwargs):
    return FakeResponse(NOTIFY_OK)


class ShopFixture(TestCase):
    """A shop with an owner, a store manager and a cashier, and one sale today."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Kilimani')
        self.owner = User.objects.create_user(username='owner', password='x', entity=self.entity,
                                              email='owner@example.com', phone='255700000009')
        StoreRole.objects.create(user=self.owner, store=None, role=Role.ENTITY_ADMIN)
        self.manager = User.objects.create_user(username='mgr', password='x', entity=self.entity,
                                                email='mgr@example.com', phone='255700000001')
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity,
                                           email='c@example.com', phone='255700000002')
        StoreRole.objects.create(user=cashier, store=self.store, role=Role.CASHIER)
        for key in ('email_notifier', 'sms_notifier'):
            ModuleEnablement.objects.create(module=ModuleRegistry.objects.get(key=key), entity=self.entity, enabled=True)

        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        product = Product.objects.create(entity=self.entity, name='Paracetamol', uom=uom)
        Price.objects.create(entity=self.entity, product=product, unit_price=Decimal('500'))
        StockBatch.objects.create(store=self.store, product=product, batch_no='B', expiry_date=date(2030, 1, 1),
                                  qty_on_hand=Decimal('100'))
        Shift.objects.create(store=self.store, cashier=cashier)
        sale = Sale.objects.create(store=self.store)
        sale.add_product(product=product, qty=Decimal('4'))
        sale.complete(user=cashier, payment_method=PaymentMethod.objects.get(implementation='cash'),
                      amount_tendered=Decimal('2000'))


@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', **NOTIFY)
class DailySummaryTests(ShopFixture):
    def run_command(self):
        with mock.patch('urllib.request.urlopen', side_effect=fake_send) as urlopen, \
                mock.patch('django.core.mail.get_connection', return_value=mail.get_connection(
                    'django.core.mail.backends.locmem.EmailBackend')):
            call_command('send_daily_summaries', stdout=StringIO())
        return urlopen

    def sms_bodies(self, urlopen):
        return [json.loads(call[0][0].data) for call in urlopen.call_args_list]

    def test_only_the_owner_gets_the_sms(self):
        urlopen = self.run_command()
        sms = self.sms_bodies(urlopen)
        self.assertEqual([s['phone_number'] for s in sms], ['255700000009'])
        self.assertIn('Kilimani', sms[0]['message'])
        self.assertIn('Sales TZS 2,000 (1)', sms[0]['message'])
        self.assertIn('Cash 2,000', sms[0]['message'])
        self.assertIn('No EFD no: 1', sms[0]['message'])
        batch = SmsBatch.objects.get()
        self.assertEqual((batch.status, batch.sent_count), (SmsBatch.Status.COMPLETED, 1))
        message = batch.messages.get()
        self.assertEqual((message.phone, message.provider_message_id), ('+255700000009', 'm-1'))
        self.assertLessEqual(message.segments, 3)

    def test_emails_still_go_to_managers_and_admins(self):
        self.run_command()
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['mgr@example.com', 'owner@example.com'])
        self.assertIn('Sales: TZS 2,000 from 1 sale(s)', mail.outbox[0].body)

    def test_managers_too_when_switched_on(self):
        SmsConfiguration.objects.create(entity=self.entity, daily_sales_to_managers=True)
        urlopen = self.run_command()
        self.assertEqual(sorted(s['phone_number'] for s in self.sms_bodies(urlopen)),
                         ['255700000001', '255700000009'])

    def test_summaries_use_the_recipients_language(self):
        self.owner.language = 'sw'
        self.owner.save()
        urlopen = self.run_command()
        message = self.sms_bodies(urlopen)[0]['message']
        self.assertIn('Mauzo TZS 2,000 (1)', message)
        self.assertIn('Fedha taslimu 2,000', message)

    def test_shop_language_overrides(self):
        SmsConfiguration.objects.create(entity=self.entity, language='sw')
        self.assertIn('Mauzo TZS', self.sms_bodies(self.run_command())[0]['message'])

    def test_edited_template_is_used(self):
        ensure_templates(self.entity)
        SmsTemplate.objects.filter(entity=self.entity, language='en').update(body='{shop}: TZS {sales_total}')
        self.assertEqual(self.sms_bodies(self.run_command())[0]['message'], 'Firm A: TZS 2,000')

    def test_running_twice_does_not_resend(self):
        self.run_command()
        urlopen = self.run_command()
        urlopen.assert_not_called()
        self.assertEqual(SmsBatch.objects.count(), 1)
        self.assertEqual(NotificationLog.objects.filter(success=True).count(), 2)

    def test_switched_off_sends_nothing(self):
        ModuleEnablement.objects.filter(module__key='sms_notifier').update(enabled=False)
        self.run_command().assert_not_called()
        self.assertFalse(SmsBatch.objects.exists())

    def test_skipped_recipients_are_recorded_with_the_reason(self):
        second = User.objects.create_user(username='owner2', password='x', entity=self.entity, phone='')
        StoreRole.objects.create(user=second, store=None, role=Role.ENTITY_ADMIN)
        third = User.objects.create_user(username='owner3', password='x', entity=self.entity, phone='0222123456')
        StoreRole.objects.create(user=third, store=None, role=Role.ENTITY_ADMIN)
        fourth = User.objects.create_user(username='owner4', password='x', entity=self.entity, phone='+255 700 000 009')
        StoreRole.objects.create(user=fourth, store=None, role=Role.ENTITY_ADMIN)
        self.run_command()
        reasons = dict(SmsMessage.objects.values_list('recipient__username', 'skip_reason'))
        self.assertEqual(reasons, {'owner': '', 'owner2': 'no_phone', 'owner3': 'invalid_phone', 'owner4': 'duplicate'})
        self.assertEqual(SmsBatch.objects.get().skipped_count, 3)

    def test_too_long_and_inactive_template_are_skipped(self):
        ensure_templates(self.entity)
        SmsTemplate.objects.filter(entity=self.entity, language='en').update(body='{store} ' + 'x' * 500)
        self.run_command().assert_not_called()
        self.assertEqual(SmsMessage.objects.get().skip_reason, 'too_long')
        SmsBatch.objects.all().delete()
        SmsTemplate.objects.filter(entity=self.entity, language='en').update(is_active=False)
        self.run_command()
        self.assertEqual(SmsMessage.objects.get().skip_reason, 'no_template')

    def test_a_failed_send_is_recorded_and_can_be_resent(self):
        with mock.patch('urllib.request.urlopen', side_effect=http_error(402, {})):
            daily_sales_sms_run()
        batch = SmsBatch.objects.get()
        self.assertEqual((batch.status, batch.failed_count), (SmsBatch.Status.FAILED, 1))
        self.assertEqual(batch.messages.get().error_detail, 'insufficient_credit')

        client = APIClient()
        client.force_authenticate(self.owner)
        with mock.patch('urllib.request.urlopen', side_effect=fake_send):
            res = client.post(f'/api/notifications/sms/batches/{batch.pk}/resend-failed/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data['status'], res.data['sent_count'], res.data['failed_count']), ('COMPLETED', 1, 0))

    def run_at(self, hour, minute):
        now = timezone.localtime().replace(hour=hour, minute=minute, second=0, microsecond=0)
        with mock.patch('urllib.request.urlopen', side_effect=fake_send) as urlopen:
            daily_sales_sms_run(now)
        return sorted(s['phone_number'] for s in self.sms_bodies(urlopen))

    @override_settings(DAILY_SUMMARY_TIME='21:30')
    def test_each_owner_gets_it_at_their_own_time(self):
        self.owner.daily_sms_time = time(18, 0)
        self.owner.save()
        second = User.objects.create_user(username='owner2', password='x', entity=self.entity, phone='255700000008')
        StoreRole.objects.create(user=second, store=None, role=Role.ENTITY_ADMIN)
        self.assertEqual(self.run_at(17, 55), [])
        self.assertEqual(self.run_at(18, 0), ['255700000009'])
        self.assertEqual(self.run_at(18, 5), [])
        self.assertEqual(self.run_at(21, 30), ['255700000008'])
        self.assertEqual(self.run_at(21, 35), [])
        self.assertEqual(SmsBatch.objects.count(), 2)

    @override_settings(DAILY_SUMMARY_TIME='21:30')
    def test_managers_get_it_at_the_default_time(self):
        SmsConfiguration.objects.create(entity=self.entity, daily_sales_to_managers=True)
        self.owner.daily_sms_time = time(19, 0)
        self.owner.save()
        self.assertEqual(self.run_at(19, 0), ['255700000009'])
        self.assertEqual(self.run_at(21, 30), ['255700000001'])

    def test_emails_wait_for_the_default_time(self):
        if timezone.localtime().time() >= time(23, 55):
            self.skipTest('too close to midnight')
        with self.settings(DAILY_SUMMARY_TIME='23:55'):
            self.run_command()
        self.assertEqual(len(mail.outbox), 0)
        self.run_command()
        self.assertEqual(len(mail.outbox), 2)

    def test_platform_admin_sets_an_owners_time(self):
        api = APIClient()
        api.force_authenticate(User.objects.create_superuser(username='root', password='x', email='r@example.com'))
        url = f'/api/core/users/{self.owner.pk}/'
        self.assertEqual(api.patch(url, {'daily_sms_time': '18:07'}, format='json').status_code, 400)
        res = api.patch(url, {'daily_sms_time': '18:15'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.daily_sms_time, time(18, 15))
        shops = api.get('/api/platform/shops/').data
        shops = shops['results'] if isinstance(shops, dict) else shops
        self.assertEqual(shops[0]['owners'][0]['daily_sms_time'], '18:15:00')
        self.assertEqual(api.patch(url, {'daily_sms_time': None}, format='json').status_code, 200)


@override_settings(**NOTIFY)
class SmsApiTests(ShopFixture):
    """The owner's screens: settings, templates, preview, send, log."""

    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_preview_saves_nothing(self):
        res = self.api.post('/api/notifications/sms/preview/', {'kind': 'DAILY_SALES_SUMMARY'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual((res.data['would_send'], res.data['skipped']), (1, 0))
        self.assertIn('Sales TZS 2,000', res.data['samples'][0]['body'])
        self.assertFalse(SmsBatch.objects.exists())

    def test_dry_run_saves_without_sending(self):
        with mock.patch('urllib.request.urlopen') as urlopen:
            res = self.api.post('/api/notifications/sms/send/', {'kind': 'DAILY_SALES_SUMMARY', 'dry_run': True},
                                format='json')
        self.assertEqual(res.status_code, 201, res.content)
        urlopen.assert_not_called()
        self.assertTrue(SmsBatch.objects.get().dry_run)

    def test_send_now_and_log(self):
        with mock.patch('urllib.request.urlopen', side_effect=fake_send):
            res = self.api.post('/api/notifications/sms/send/', {'kind': 'DAILY_SALES_SUMMARY', 'language': 'sw'},
                                format='json')
        self.assertEqual(res.data['sent_count'], 1)
        self.assertIn('Mauzo', res.data['messages'][0]['body'])
        log = self.api.get('/api/notifications/sms/batches/', {'status': 'COMPLETED'})
        self.assertEqual(log.data['count'] if isinstance(log.data, dict) else len(log.data), 1)

    def test_templates_are_validated(self):
        templates = self.api.get('/api/notifications/sms/templates/', {'language': 'sw'}).data
        templates = templates['results'] if isinstance(templates, dict) else templates
        self.assertEqual(len(templates), 1)
        url = f"/api/notifications/sms/templates/{templates[0]['id']}/"
        self.assertEqual(self.api.patch(url, {'body': 'Hi {nope}'}, format='json').status_code, 400)
        self.assertEqual(self.api.patch(url, {'body': 'Mauzo {sales_total}'}, format='json').status_code, 200)

    def test_config_can_only_lower_the_limits(self):
        with self.settings(SMS_MAX_SEGMENTS=3):
            res = self.api.patch('/api/notifications/sms/config/', {'max_segments': 9}, format='json')
            self.assertEqual(res.data['effective_max_segments'], 3)
            res = self.api.patch('/api/notifications/sms/config/', {'max_segments': 2}, format='json')
            self.assertEqual(res.data['effective_max_segments'], 2)

    def test_managers_cannot_use_the_sms_screens(self):
        self.api.force_authenticate(self.manager)
        self.assertEqual(self.api.get('/api/notifications/sms/batches/').status_code, 403)
        self.assertEqual(self.api.post('/api/notifications/sms/send/', {'kind': 'DAILY_SALES_SUMMARY'},
                                       format='json').status_code, 403)

    def test_other_shops_batches_are_hidden(self):
        other = Entity.objects.create(name='Firm B')
        SmsBatch.objects.create(entity=other, kind='DAILY_SALES_SUMMARY')
        log = self.api.get('/api/notifications/sms/batches/').data
        self.assertEqual(log['count'] if isinstance(log, dict) else len(log), 0)
