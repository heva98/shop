from datetime import date
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User
from inventory.models import StockBatch
from payments.models import PaymentMethod
from pos.models import Shift
from pricing.models import Price

from .models import Customer


class CreditTestBase(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Kariakoo')
        self.cash = PaymentMethod.objects.get(implementation=PaymentMethod.Implementation.CASH)
        self.mobile = PaymentMethod.objects.get(implementation=PaymentMethod.Implementation.MOBILE_MONEY)
        self.cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.cashier, store=self.store, role=Role.CASHIER)
        self.manager = User.objects.create_user(username='manager', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)
        self.customer = Customer.objects.create(entity=self.entity, name='Mama Neema', phone='255712000001',
                                                credit_limit=Decimal('20000'))

    def credit_sale(self, amount='3000'):
        """A completed sale of one 3000 packet, `amount` of it on credit."""
        uom = UnitOfMeasure.objects.get_or_create(entity=self.entity, name='Packet', defaults={'unit_value': 1})[0]
        sugar = Product.objects.get_or_create(entity=self.entity, name='Sugar 1kg', defaults={'uom': uom})[0]
        Price.objects.get_or_create(entity=self.entity, product=sugar, defaults={'unit_price': Decimal('3000')})
        StockBatch.objects.get_or_create(store=self.store, product=sugar, defaults={'qty_on_hand': 100,
                                                                                     'expiry_date': date(2030, 1, 1)})
        self.client.force_authenticate(self.cashier)
        if not Shift.objects.filter(cashier=self.cashier, closed_at__isnull=True).exists():
            self.client.post('/api/pos/shifts/', {'store': str(self.store.id), 'opening_float': '0'})
        sale = self.client.post('/api/pos/sales/', {
            'store': str(self.store.id), 'items': [{'product': str(sugar.id), 'qty': '1'}]}, format='json').data
        response = self.client.post(f'/api/pos/sales/{sale["id"]}/complete/', {
            'payment_method': str(self.cash.id), 'amount_tendered': str(Decimal('3000') - Decimal(amount)),
            'customer': str(self.customer.id), 'credit_amount': amount}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def pay(self, amount, method=None, **extra):
        return self.client.post('/api/credit/payments/', {
            'customer': str(self.customer.id), 'store': str(self.store.id), 'amount': amount,
            'payment_method': str((method or self.cash).id), **extra})


class CustomerTests(CreditTestBase):
    def test_list_shows_what_each_customer_owes(self):
        self.credit_sale('3000')
        self.client.force_authenticate(self.cashier)
        rows = self.client.get('/api/credit/customers/').data['results']
        self.assertEqual([(r['name'], r['owing']) for r in rows], [('Mama Neema', '3000.00')])
        self.assertEqual(self.client.get('/api/credit/customers/', {'owing': 'true'}).data['count'], 1)

    def test_a_cashier_can_register_a_customer_but_they_get_no_credit_until_a_manager_says(self):
        self.client.force_authenticate(self.cashier)
        response = self.client.post('/api/credit/customers/', {'name': 'Baraka', 'phone': '255 754 000 002',
                                                               'credit_limit': '100000'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual((response.data['phone'], response.data['credit_limit']), ('255754000002', '0.00'))
        refused = self.client.patch(f'/api/credit/customers/{response.data["id"]}/', {'credit_limit': '5000'})
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.manager)
        ok = self.client.patch(f'/api/credit/customers/{response.data["id"]}/', {'credit_limit': '5000'})
        self.assertEqual(ok.data['credit_limit'], '5000.00')

    def test_phone_numbers_are_unique_within_the_shop(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/credit/customers/', {'name': 'Someone', 'phone': '255712000001'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Mama Neema', str(response.data['phone']))

    def test_a_customer_with_history_cannot_be_removed(self):
        self.credit_sale()
        self.client.force_authenticate(self.manager)
        response = self.client.delete(f'/api/credit/customers/{self.customer.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_other_firms_customers_are_invisible(self):
        other = Entity.objects.create(name='Firm B')
        Customer.objects.create(entity=other, name='Stranger')
        self.client.force_authenticate(self.manager)
        names = [r['name'] for r in self.client.get('/api/credit/customers/').data['results']]
        self.assertEqual(names, ['Mama Neema'])


class PaymentTests(CreditTestBase):
    def test_a_cash_repayment_at_the_till_counts_in_the_drawer(self):
        self.credit_sale('3000')
        response = self.pay('2000')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(self.customer.balance(), Decimal('1000'))
        summary = Shift.objects.get(cashier=self.cashier).summary()
        self.assertEqual((summary['cash_repayments'], summary['expected_cash']), (Decimal('2000'), Decimal('2000')))

    def test_cash_without_a_shift_is_refused_for_a_cashier(self):
        self.client.force_authenticate(self.cashier)
        response = self.pay('1000')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Open a shift', response.data['detail'])

    def test_mobile_money_needs_a_reference(self):
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.pay('1000', method=self.mobile).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.pay('1000', method=self.mobile, reference='QK7Y2').status_code, status.HTTP_201_CREATED)

    def test_only_a_manager_voids_a_payment_and_the_balance_comes_back(self):
        self.credit_sale('3000')
        payment = self.pay('3000').data
        self.assertEqual(self.customer.balance(), Decimal('0'))
        refused = self.client.post(f'/api/credit/payments/{payment["id"]}/void/', {'reason': 'Typed twice'})
        self.assertEqual(refused.status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.manager)
        ok = self.client.post(f'/api/credit/payments/{payment["id"]}/void/', {'reason': 'Typed twice'})
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.assertEqual(self.customer.balance(), Decimal('3000'))
        self.assertEqual(Shift.objects.get(cashier=self.cashier).summary()['cash_repayments'], Decimal('0'))

    def test_statement_runs_the_balance_in_date_order(self):
        self.credit_sale('3000')
        self.credit_sale('2000')
        self.pay('4000')
        self.client.force_authenticate(self.manager)
        data = self.client.get(f'/api/credit/customers/{self.customer.id}/statement/').data
        self.assertEqual([(r['kind'], r['balance']) for r in data['rows']],
                         [('sale', Decimal('3000')), ('sale', Decimal('5000')), ('payment', Decimal('1000'))])
        self.assertEqual(data['owing'], Decimal('1000'))
