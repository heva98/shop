import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from audit.models import AuditEvent
from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User
from credit.models import Customer
from inventory.models import StockBatch, StockLedger
from payments.models import PaymentMethod
from pos.models import Sale, Shift
from pricing.models import Price, Promotion


def _payment_methods():
    # Migration 0003 seeds these; tests reuse them rather than duplicating.
    return (
        PaymentMethod.objects.get(implementation=PaymentMethod.Implementation.CASH),
        PaymentMethod.objects.get(implementation=PaymentMethod.Implementation.MOBILE_MONEY),
    )


class SaleWriteScopingTests(APITestCase):
    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A')
        self.entity_b = Entity.objects.create(name='Firm B')
        self.store_a = Store.objects.create(entity=self.entity_a, name='A')
        self.store_b = Store.objects.create(entity=self.entity_b, name='B')
        self.cashier_a = User.objects.create_user(username='cashier_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.cashier_a, store=self.store_a, role=Role.CASHIER)

        self.store_a2 = Store.objects.create(entity=self.entity_a, name='A2')

    def test_cannot_create_sale_under_another_entitys_store(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/pos/sales/', {'store': str(self.store_b.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_cannot_create_sale_for_sibling_store_in_same_entity(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/pos/sales/', {'store': str(self.store_a2.id)})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_client_generated_id_is_honored(self):
        """The offline-sync contract (architecture.txt §3/§4): a till that
        created this Sale while offline already minted its id locally —
        the server must use that id, not assign a different one, or two
        stores' outboxes could never merge without collision."""
        self.client.force_authenticate(self.cashier_a)
        client_id = str(uuid.uuid4())
        response = self.client.post('/api/pos/sales/', {'id': client_id, 'store': str(self.store_a.id)})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['id'], client_id)
        self.assertTrue(Sale.objects.filter(id=client_id).exists())

    def test_omitting_id_still_falls_back_to_a_server_generated_one(self):
        self.client.force_authenticate(self.cashier_a)
        response = self.client.post('/api/pos/sales/', {'store': str(self.store_a.id)})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['id'])


class PosTestBase(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A')
        self.cash, self.mobile_money = _payment_methods()
        self.cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.cashier, store=self.store, role=Role.CASHIER)
        self.manager = User.objects.create_user(username='manager', password='secret-pw', entity=self.entity)
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)

        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Strip', unit_value=10)
        self.product = Product.objects.create(
            entity=self.entity, name='Paracetamol', uom=uom,
            vat_class=Product.VatClass.STANDARD,
        )
        Price.objects.create(entity=self.entity, product=self.product, unit_price=Decimal('1180'))
        self.expires_soon = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='SOON',
            expiry_date=date(2030, 1, 1), qty_on_hand=Decimal('2'),
        )
        self.expires_later = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='LATER',
            expiry_date=date(2031, 1, 1), qty_on_hand=Decimal('50'),
        )
        self.client.force_authenticate(self.cashier)

    def open_shift(self, user=None, opening_float='10000'):
        self.client.force_authenticate(user or self.cashier)
        response = self.client.post('/api/pos/shifts/', {'store': str(self.store.id), 'opening_float': opening_float})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data['id']

    def new_sale(self, qty='5', product=None):
        response = self.client.post('/api/pos/sales/', {
            'store': str(self.store.id),
            'items': [{'product': str((product or self.product).id), 'qty': qty}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def complete(self, sale_id, **payment):
        payload = {'payment_method': str(self.cash.id), 'amount_tendered': '10000', **payment}
        return self.client.post(f'/api/pos/sales/{sale_id}/complete/', payload, format='json')


class SalePricingAndFefoTests(PosTestBase):
    def test_items_are_priced_server_side_and_split_across_batches_by_fefo(self):
        sale = self.new_sale(qty='5')
        self.assertEqual(len(sale['lines']), 2)
        self.assertEqual({line['unit_price'] for line in sale['lines']}, {'1180.00'})
        self.assertEqual(sale['total'], '5900.00')
        self.assertEqual(sale['vat_total'], '900.00')

        self.open_shift()
        response = self.complete(sale['id'])
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.expires_soon.refresh_from_db()
        self.expires_later.refresh_from_db()
        self.assertEqual(self.expires_soon.qty_on_hand, Decimal('0'))
        self.assertEqual(self.expires_later.qty_on_hand, Decimal('47'))

    def test_a_price_sent_by_the_till_is_ignored(self):
        sale = self.new_sale(qty='1')
        response = self.client.post(f'/api/pos/sales/{sale["id"]}/add_line/', {
            'product': str(self.product.id), 'qty': '1', 'unit_price': '1', 'vat_class': 'exempt',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['total'], '2360.00')

    def test_product_without_a_price_cannot_be_sold(self):
        Price.objects.all().delete()
        response = self.client.post('/api/pos/sales/', {
            'store': str(self.store.id), 'items': [{'product': str(self.product.id), 'qty': '1'}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('no selling price', response.data['detail'])
        self.assertFalse(Sale.objects.exists(), 'a failed create must not leave a half-built sale behind')

    def test_add_line_rejects_more_than_is_in_stock(self):
        sale = self.new_sale(qty='1')
        response = self.client.post(f'/api/pos/sales/{sale["id"]}/add_line/', {
            'product': str(self.product.id), 'qty': '999',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SaleLockingTests(PosTestBase):
    def test_sales_cannot_be_edited_or_deleted_through_the_api(self):
        sale = self.new_sale()
        self.open_shift()
        self.complete(sale['id'])
        url = f'/api/pos/sales/{sale["id"]}/'
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.patch(url, {'store': str(self.store.id)}).status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_completed_sale_cannot_be_changed_or_completed_twice(self):
        sale = self.new_sale()
        self.open_shift()
        self.assertEqual(self.complete(sale['id']).status_code, status.HTTP_200_OK)
        self.assertEqual(self.complete(sale['id']).status_code, status.HTTP_400_BAD_REQUEST)
        add = self.client.post(f'/api/pos/sales/{sale["id"]}/add_line/', {'product': str(self.product.id), 'qty': '1'})
        self.assertEqual(add.status_code, status.HTTP_400_BAD_REQUEST)
        cancel = self.client.post(f'/api/pos/sales/{sale["id"]}/cancel/')
        self.assertEqual(cancel.status_code, status.HTTP_400_BAD_REQUEST)
        self.expires_later.refresh_from_db()
        self.assertEqual(self.expires_later.qty_on_hand, Decimal('47'), 'stock deducted exactly once')

    def test_open_sale_can_be_cancelled(self):
        sale = self.new_sale()
        response = self.client.post(f'/api/pos/sales/{sale["id"]}/cancel/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Sale.objects.filter(id=sale['id']).exists())


class SaleCompletionRulesTests(PosTestBase):
    def test_selling_requires_an_open_shift(self):
        sale = self.new_sale()
        response = self.complete(sale['id'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('shift', response.data['detail'])

    def test_cash_must_cover_the_total(self):
        sale = self.new_sale()
        self.open_shift()
        response = self.complete(sale['id'], amount_tendered='100')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_completion_records_cashier_number_shift_and_change(self):
        sale = self.new_sale()
        shift_id = self.open_shift()
        response = self.complete(sale['id'], amount_tendered='10000')
        self.assertEqual(response.data['status'], 'completed')
        self.assertEqual(response.data['number'], 1)
        self.assertEqual(response.data['cashier'], self.cashier.id)
        self.assertEqual(str(response.data['shift']), shift_id)
        self.assertEqual(response.data['change_due'], '4100.00')

        second = self.new_sale(qty='1')
        self.assertEqual(self.complete(second['id']).data['number'], 2)

    def test_mobile_money_requires_a_reference(self):
        sale = self.new_sale()
        self.open_shift()
        missing = self.complete(sale['id'], payment_method=str(self.mobile_money.id), amount_tendered=None)
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        ok = self.complete(sale['id'], payment_method=str(self.mobile_money.id), payment_reference='QK7Y2ZT1')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.assertEqual(ok.data['payment_reference'], 'QK7Y2ZT1')

    def test_inactive_payment_method_is_refused(self):
        self.mobile_money.is_active = False
        self.mobile_money.save()
        sale = self.new_sale()
        self.open_shift()
        response = self.complete(sale['id'], payment_method=str(self.mobile_money.id), payment_reference='X')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_goods_that_never_expire_sell_after_dated_stock(self):
        undated = StockBatch.objects.create(store=self.store, product=self.product, qty_on_hand=Decimal('10'))
        self.expires_later.qty_on_hand = 0
        self.expires_later.save()
        sale = self.new_sale(qty='4')
        self.assertEqual([str(line['batch']) for line in sale['lines']], [str(self.expires_soon.id), str(undated.id)])


class CreditSaleTests(PosTestBase):
    def setUp(self):
        super().setUp()
        self.customer = Customer.objects.create(entity=self.entity, name='Mama Neema', credit_limit=Decimal('5000'))

    def test_part_of_a_sale_goes_on_the_customers_account(self):
        sale = self.new_sale(qty='3')  # 3540
        self.open_shift()
        response = self.complete(sale['id'], customer=str(self.customer.id), credit_amount='3000', amount_tendered='1000')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual((response.data['credit_amount'], response.data['paid_amount']), ('3000.00', '540.00'))
        self.assertEqual(response.data['customer_name'], 'Mama Neema')
        self.assertEqual(self.customer.balance(), Decimal('3000'))
        summary = Shift.objects.get().summary()
        methods = {row['payment_method']: row['total'] for row in summary['by_payment_method']}
        self.assertEqual(methods, {'Cash': Decimal('540.00'), 'On credit': Decimal('3000.00')})
        self.assertEqual(summary['expected_cash'], Decimal('10540.00'))

    def test_credit_limit_is_enforced(self):
        sale = self.new_sale(qty='5')  # 5900
        self.open_shift()
        response = self.complete(sale['id'], customer=str(self.customer.id), credit_amount='5900')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('credit limit', response.data['detail'])

    def test_credit_needs_a_customer(self):
        sale = self.new_sale(qty='1')
        self.open_shift()
        response = self.complete(sale['id'], credit_amount='1180')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_voiding_a_credit_sale_clears_what_the_customer_owes(self):
        sale = self.new_sale(qty='1')
        self.open_shift()
        self.complete(sale['id'], customer=str(self.customer.id), credit_amount='1180')
        self.assertEqual(self.customer.balance(), Decimal('1180'))
        self.client.force_authenticate(self.manager)
        self.client.post(f'/api/pos/sales/{sale["id"]}/void/', {'reason': 'Wrong customer'})
        self.assertEqual(self.customer.balance(), Decimal('0'))

    def test_offline_credit_sale_over_the_limit_is_still_recorded(self):
        shift_id = self.open_shift()
        response = self.client.post('/api/pos/sales/record/', {
            'id': str(uuid.uuid4()), 'store': str(self.store.id), 'shift': shift_id,
            'items': [{'product': str(self.product.id), 'qty': '5', 'unit_price': '1180'}],
            'payment_method': str(self.cash.id), 'amount_tendered': '0',
            'customer': str(self.customer.id), 'credit_amount': '5900',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(self.customer.balance(), Decimal('5900'))


class DiscountTests(PosTestBase):
    def test_line_and_sale_discounts_reduce_the_total_and_vat(self):
        response = self.client.post('/api/pos/sales/', {
            'store': str(self.store.id), 'items': [{'product': str(self.product.id), 'qty': '5', 'discount': '100'}],
        }, format='json')
        sale = response.data
        self.assertEqual((sale['total'], sale['discount_total']), ('5800.00', '100.00'))
        self.open_shift()
        done = self.complete(sale['id'], discount='300')
        self.assertEqual(done.status_code, status.HTTP_200_OK, done.data)
        self.assertEqual((done.data['total'], done.data['discount_total']), ('5500.00', '400.00'))
        self.assertEqual(done.data['vat_total'], '838.98')
        self.assertEqual(sum(Decimal(line['amount']) for line in done.data['lines']), Decimal('5500'))

    def test_cashier_needs_a_manager_for_a_discount_over_the_limit(self):
        sale = self.new_sale(qty='5')  # 5900; the default limit is 10%
        self.open_shift()
        refused = self.complete(sale['id'], discount='1000')
        self.assertEqual(refused.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('manager must approve', refused.data['detail'])
        wrong = self.complete(sale['id'], discount='1000', approver_username='manager', approver_password='nope')
        self.assertEqual(wrong.status_code, status.HTTP_403_FORBIDDEN)
        ok = self.complete(sale['id'], discount='1000', approver_username='manager', approver_password='secret-pw')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.assertEqual(Sale.objects.get().discount_approved_by, self.manager)
        self.assertTrue(AuditEvent.objects.filter(action='discount_given').exists())

    def test_a_discount_within_the_limit_needs_no_approval(self):
        sale = self.new_sale(qty='5')
        self.open_shift()
        self.assertEqual(self.complete(sale['id'], discount='590').status_code, status.HTTP_200_OK)

    def test_discount_cannot_exceed_the_total(self):
        sale = self.new_sale(qty='1')
        self.open_shift(user=self.manager)
        self.assertEqual(self.complete(sale['id'], discount='5000').status_code, status.HTTP_400_BAD_REQUEST)


class PromotionPriceTests(PosTestBase):
    def test_a_running_promotion_sets_the_till_price(self):
        today = timezone.localdate()
        Promotion.objects.create(entity=self.entity, name='Offer', product=self.product, promo_price=Decimal('1000'),
                                 starts_on=today, ends_on=today + timedelta(days=2))
        Promotion.objects.create(entity=self.entity, name='Next week', product=self.product, promo_price=Decimal('500'),
                                 starts_on=today + timedelta(days=7), ends_on=today + timedelta(days=9))
        sale = self.new_sale(qty='2')
        self.assertEqual(sale['total'], '2000.00')
        till = self.client.get('/api/pos/till/', {'store': str(self.store.id)}).data
        price = next(p for p in till['prices'] if p['product'] == str(self.product.id) and p['uom'] is None)
        self.assertEqual((price['unit_price'], price['regular_price'], price['promotion']),
                         (Decimal('1000'), Decimal('1180'), 'Offer'))

    def test_a_store_promotion_wins_over_a_firm_wide_one(self):
        today = timezone.localdate()
        Promotion.objects.create(entity=self.entity, name='Everywhere', product=self.product,
                                 promo_price=Decimal('1100'), starts_on=today, ends_on=today)
        Promotion.objects.create(entity=self.entity, store=self.store, name='Here', product=self.product,
                                 promo_price=Decimal('900'), starts_on=today, ends_on=today)
        self.assertEqual(self.new_sale(qty='1')['total'], '900.00')


class FiscalReceiptTests(PosTestBase):
    def test_standalone_efd_asks_for_the_receipt_number_and_records_it(self):
        sale = self.new_sale()
        self.open_shift()
        response = self.complete(sale['id'])
        self.assertTrue(response.data['fiscal_result']['pending_manual'])
        self.assertEqual(response.data['efd_receipt_no'], '')

        recorded = self.client.post(f'/api/pos/sales/{sale["id"]}/record_fiscal/', {'receipt_number': '00123'})
        self.assertEqual(recorded.status_code, status.HTTP_200_OK, recorded.data)
        self.assertEqual(recorded.data['efd_receipt_no'], '00123')

        again = self.client.post(f'/api/pos/sales/{sale["id"]}/record_fiscal/', {'receipt_number': '00124'})
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)

    def test_the_same_efd_number_cannot_be_used_twice(self):
        self.open_shift()
        first, second = self.new_sale(qty='1'), self.new_sale(qty='1')
        self.complete(first['id'])
        self.complete(second['id'])
        self.client.post(f'/api/pos/sales/{first["id"]}/record_fiscal/', {'receipt_number': '00123'})
        dup = self.client.post(f'/api/pos/sales/{second["id"]}/record_fiscal/', {'receipt_number': '00123'})
        self.assertEqual(dup.status_code, status.HTTP_400_BAD_REQUEST)


class VoidTests(PosTestBase):
    def setUp(self):
        super().setUp()
        self.sale = self.new_sale(qty='5')
        self.open_shift()
        self.complete(self.sale['id'])
        self.url = f'/api/pos/sales/{self.sale["id"]}/void/'

    def test_cashier_cannot_void_without_manager_approval(self):
        response = self.client.post(self.url, {'reason': 'Customer changed mind'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        bad = self.client.post(self.url, {
            'reason': 'Customer changed mind', 'approver_username': 'manager', 'approver_password': 'wrong',
        })
        self.assertEqual(bad.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Sale.objects.get(id=self.sale['id']).status, Sale.Status.COMPLETED)

    def test_another_cashier_cannot_approve(self):
        User.objects.create_user(username='cashier2', password='pw2', entity=self.entity)
        StoreRole.objects.create(user=User.objects.get(username='cashier2'), store=self.store, role=Role.CASHIER)
        response = self.client.post(self.url, {
            'reason': 'Wrong item', 'approver_username': 'cashier2', 'approver_password': 'pw2',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_override_voids_and_returns_stock_to_the_same_batches(self):
        response = self.client.post(self.url, {
            'reason': 'Wrong item', 'approver_username': 'manager', 'approver_password': 'secret-pw',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'voided')
        self.assertEqual(response.data['void_approved_by_name'], 'manager')
        self.expires_soon.refresh_from_db()
        self.expires_later.refresh_from_db()
        self.assertEqual(self.expires_soon.qty_on_hand, Decimal('2'))
        self.assertEqual(self.expires_later.qty_on_hand, Decimal('50'))
        self.assertEqual(StockLedger.objects.filter(ledger_type=StockLedger.LedgerType.SALE_VOID).count(), 2)

        twice = self.client.post(self.url, {'reason': 'again', 'approver_username': 'manager', 'approver_password': 'secret-pw'})
        self.assertEqual(twice.status_code, status.HTTP_400_BAD_REQUEST)

    def test_manager_voids_directly_and_a_reason_is_required(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(self.url, {'reason': ''}).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.post(self.url, {'reason': 'Duplicate'}).status_code, status.HTTP_200_OK)


class ShiftTests(PosTestBase):
    def test_only_one_open_shift_per_cashier(self):
        self.open_shift()
        response = self.client.post('/api/pos/shifts/', {'store': str(self.store.id), 'opening_float': '0'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_current_returns_the_callers_open_shift(self):
        self.assertIsNone(self.client.get('/api/pos/shifts/current/', {'store': str(self.store.id)}).data)
        shift_id = self.open_shift()
        self.assertEqual(str(self.client.get('/api/pos/shifts/current/', {'store': str(self.store.id)}).data['id']), shift_id)

    def test_close_produces_z_report_with_cash_variance(self):
        shift_id = self.open_shift(opening_float='10000')
        cash_sale = self.new_sale(qty='5')            # 5,900 cash
        self.complete(cash_sale['id'])
        mm_sale = self.new_sale(qty='1')              # 1,180 mobile money
        self.complete(mm_sale['id'], payment_method=str(self.mobile_money.id), payment_reference='REF1')
        voided = self.new_sale(qty='1')               # 1,180 cash, then voided
        self.complete(voided['id'])
        self.client.force_authenticate(self.manager)
        self.client.post(f'/api/pos/sales/{voided["id"]}/void/', {'reason': 'Duplicate'})
        self.client.force_authenticate(self.cashier)

        response = self.client.post(f'/api/pos/shifts/{shift_id}/close/', {'counted_cash': '15800', 'note': ''})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        z = response.data['summary']
        self.assertEqual(z['sales_count'], 2)
        self.assertEqual(z['gross_total'], Decimal('7080.00'))
        self.assertEqual(z['void_count'], 1)
        self.assertEqual(z['cash_sales'], Decimal('5900.00'))
        self.assertEqual(z['expected_cash'], Decimal('15900.00'))
        self.assertEqual(z['variance'], Decimal('-100.00'))
        self.assertFalse(Shift.objects.get(id=shift_id).is_open)

        after = self.new_sale(qty='1')
        self.assertEqual(self.complete(after['id']).status_code, status.HTTP_400_BAD_REQUEST, 'no selling after close')

    def test_another_cashier_cannot_close_my_shift(self):
        shift_id = self.open_shift()
        other = User.objects.create_user(username='c2', password='x', entity=self.entity)
        StoreRole.objects.create(user=other, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(other)
        response = self.client.post(f'/api/pos/shifts/{shift_id}/close/', {'counted_cash': '0'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SellingUnitTests(PosTestBase):
    """Stock is held in the product's own unit (Tablet); a Strip of 10 has
    its own price and converts into tablets when it comes off the batch."""

    def setUp(self):
        super().setUp()
        self.tablet = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        self.strip = UnitOfMeasure.objects.create(entity=self.entity, name='Strip of 10', unit_value=10)
        self.loose = Product.objects.create(
            entity=self.entity, name='Ibuprofen 200mg', uom=self.tablet,
            vat_class=Product.VatClass.EXEMPT,
        )
        Price.objects.create(entity=self.entity, product=self.loose, unit_price=Decimal('100'))
        Price.objects.create(entity=self.entity, product=self.loose, uom=self.strip, unit_price=Decimal('900'))
        self.first = StockBatch.objects.create(
            store=self.store, product=self.loose, batch_no='A', expiry_date=date(2030, 1, 1), qty_on_hand=Decimal('15'))
        self.second = StockBatch.objects.create(
            store=self.store, product=self.loose, batch_no='B', expiry_date=date(2031, 1, 1), qty_on_hand=Decimal('100'))
        self.open_shift()

    def sell(self, qty, uom=None):
        item = {'product': str(self.loose.id), 'qty': qty}
        if uom:
            item['uom'] = str(uom.id)
        return self.client.post('/api/pos/sales/', {'store': str(self.store.id), 'items': [item]}, format='json')

    def test_strip_is_priced_per_strip_and_deducts_tablets_across_batches(self):
        response = self.sell('2', self.strip)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['total'], '1800.00')
        lines = sorted(response.data['lines'], key=lambda l: l['batch_no'])
        self.assertEqual([(l['batch_no'], l['qty'], l['sell_qty'], l['amount']) for l in lines],
                         [('A', '15.00', '1.50', '1350.00'), ('B', '5.00', '0.50', '450.00')])
        self.assertEqual({l['unit_name'] for l in lines}, {'Strip of 10'})
        self.complete(response.data['id'])
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertEqual((self.first.qty_on_hand, self.second.qty_on_hand), (Decimal('0'), Decimal('95')))

    def test_loose_tablets_use_the_base_price(self):
        response = self.sell('3')
        self.assertEqual(response.data['total'], '300.00')

    def test_a_unit_without_its_own_price_cannot_be_sold(self):
        box = UnitOfMeasure.objects.create(entity=self.entity, name='Box of 100', unit_value=100)
        response = self.sell('1', box)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('per Box of 100', response.data['detail'])

    def test_sale_totals_and_reports_use_the_stored_amount(self):
        sale = self.sell('1', self.strip).data
        self.complete(sale['id'])
        report = self.client.get('/api/reports/sales/', {'store': str(self.store.id)}).data
        self.assertEqual(report['summary']['gross_total'], Decimal('900.00'))


class OfflineSaleTests(PosTestBase):
    """POST /sales/record/: a sale the till rang up from its own copy of
    the catalog, sent once the connection is back (architecture.txt §4)."""

    def offline_sale(self, **overrides):
        payload = {
            'id': str(uuid.uuid4()), 'store': str(self.store.id),
            'items': [{'product': str(self.product.id), 'qty': '3', 'unit_price': '1180'}],
            'payment_method': str(self.cash.id), 'amount_tendered': '5000',
            'completed_at': '2026-10-25T08:15:00Z', **overrides,
        }
        return payload, self.client.post('/api/pos/sales/record/', payload, format='json')

    def test_records_the_whole_sale_once_however_often_it_is_sent(self):
        self.open_shift()
        payload, response = self.offline_sale()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['id'], payload['id'])
        self.assertEqual(response.data['status'], 'completed')
        self.assertEqual(response.data['total'], '3540.00')
        self.assertTrue(response.data['completed_at'].startswith('2026-10-25'))

        again = self.client.post('/api/pos/sales/record/', payload, format='json')
        self.assertEqual(again.status_code, status.HTTP_200_OK, again.data)
        self.assertEqual(again.data['number'], response.data['number'])
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(StockLedger.objects.filter(ref_id=payload['id']).count(), 2)  # FEFO: 2 + 1, once

    def test_offline_sale_keeps_the_price_charged_and_is_audited(self):
        from audit.models import AuditEvent
        self.open_shift()
        Price.objects.update(unit_price=Decimal('1500'))
        _, response = self.offline_sale()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['total'], '3540.00')
        self.assertTrue(AuditEvent.objects.filter(action=AuditEvent.Action.OFFLINE_SALE_PRICE).exists())

    def test_a_sale_made_just_now_is_refused_when_the_price_changed(self):
        self.open_shift()
        Price.objects.update(unit_price=Decimal('1500'))
        _, response = self.offline_sale(strict=True)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('1,500', response.data['detail'])
        self.assertEqual(Sale.objects.count(), 0)

    def test_not_enough_stock_leaves_nothing_behind_so_it_can_be_retried(self):
        self.open_shift()
        _, response = self.offline_sale(items=[{'product': str(self.product.id), 'qty': '100', 'unit_price': '1180'}])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Sale.objects.count(), 0)
        self.expires_later.refresh_from_db()
        self.assertEqual(self.expires_later.qty_on_hand, Decimal('50'))

    def test_goes_to_the_shift_it_was_rung_up_in_even_if_closed_since(self):
        shift_id = self.open_shift()
        Shift.objects.filter(pk=shift_id).update(closed_at='2026-10-25T09:00:00Z')
        _, response = self.offline_sale(shift=shift_id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['shift'], uuid.UUID(shift_id))

    def test_cannot_reuse_the_id_of_another_sale(self):
        self.open_shift()
        open_cart = self.new_sale(qty='1')
        _, response = self.offline_sale(id=open_cart['id'])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_till_snapshot_has_what_the_till_needs_to_sell_offline(self):
        self.open_shift()
        response = self.client.get('/api/pos/till/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual([p['name'] for p in response.data['products']], ['Paracetamol'])
        self.assertEqual(response.data['prices'][0]['unit_price'], Decimal('1180.00'))
        self.assertEqual(sum(b['qty_on_hand'] for b in response.data['stock']), Decimal('52'))
        self.assertIsNotNone(response.data['shift'])

    def test_till_snapshot_of_another_firms_store_is_not_found(self):
        other = Store.objects.create(entity=Entity.objects.create(name='Firm B'), name='B')
        response = self.client.get('/api/pos/till/', {'store': str(other.id)})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
