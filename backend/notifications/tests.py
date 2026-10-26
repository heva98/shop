import base64
import json
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, ModuleEnablement, ModuleRegistry, Role, Store, StoreRole, User
from inventory.models import StockBatch
from payments.models import PaymentMethod
from pos.models import Sale, Shift
from pricing.models import Price

from .channels.sms_channel import SMSChannel, SMSError
from .models import NotificationLog

BEEM = dict(SMS_PROVIDER='beem', BEEM_API_KEY='key', BEEM_SECRET_KEY='secret', BEEM_SENDER_ID='KILIMANI')


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class BeemChannelTests(TestCase):
    @override_settings(**BEEM)
    def test_sends_the_documented_request(self):
        ok = FakeResponse({'successful': True, 'code': 100, 'valid': 1, 'invalid': 0})
        with mock.patch('urllib.request.urlopen', return_value=ok) as urlopen:
            self.assertTrue(SMSChannel().send('255712345678', '', 'Hello'))
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://apisms.beem.africa/v1/send')
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(b'key:secret').decode())
        body = json.loads(request.data)
        self.assertEqual(body['source_addr'], 'KILIMANI')
        self.assertEqual(body['recipients'], [{'recipient_id': 1, 'dest_addr': '255712345678'}])

    @override_settings(**BEEM)
    def test_a_refusal_raises(self):
        bad = FakeResponse({'successful': False, 'code': 102, 'message': 'Insufficient balance'})
        with mock.patch('urllib.request.urlopen', return_value=bad), self.assertRaises(SMSError) as ctx:
            SMSChannel().send('255712345678', '', 'Hello')
        self.assertIn('Insufficient balance', str(ctx.exception))

    def test_without_a_provider_nothing_is_sent(self):
        with mock.patch('urllib.request.urlopen') as urlopen:
            self.assertFalse(SMSChannel().send('255712345678', '', 'Hello'))
        urlopen.assert_not_called()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend', **BEEM)
class DailySummaryTests(TestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Kilimani')
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

    def run_command(self):
        ok = FakeResponse({'successful': True, 'code': 100, 'valid': 1, 'invalid': 0})
        with mock.patch('urllib.request.urlopen', return_value=ok) as urlopen, \
                mock.patch('django.core.mail.get_connection', return_value=mail.get_connection(
                    'django.core.mail.backends.locmem.EmailBackend')):
            call_command('send_daily_summaries', stdout=StringIO())
        return urlopen

    def test_managers_get_sms_and_email_cashiers_do_not(self):
        urlopen = self.run_command()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['mgr@example.com'])
        self.assertIn('Sales: TZS 2,000 from 1 sale(s)', mail.outbox[0].body)
        self.assertEqual(urlopen.call_count, 1)
        sms = json.loads(urlopen.call_args[0][0].data)
        self.assertEqual(sms['recipients'][0]['dest_addr'], '255700000001')
        self.assertIn('Sales TZS 2,000 (1)', sms['message'])
        self.assertIn('NO EFD no: 1', sms['message'])
        self.assertLessEqual(len(sms['message']), 306)

    def test_running_twice_does_not_resend(self):
        self.run_command()
        urlopen = self.run_command()
        self.assertEqual(len(mail.outbox), 1, 'still only the email from the first run')
        urlopen.assert_not_called()
        self.assertEqual(NotificationLog.objects.filter(success=True).count(), 2)
