import datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Category, Product, UnitOfMeasure
from core.features import set_feature
from core.models import Entity, Role, Store, StoreRole, User
from credit.models import Customer
from inventory.models import StockBatch, StockLedger
from payments.models import PaymentMethod
from pos.models import Sale, SaleLine

TZ = timezone.get_current_timezone()


def at(y, m, d, hour=12):
    return datetime.datetime(y, m, d, hour, tzinfo=TZ)


class QueryFixture(APITestCase):
    """Two stores of one firm, plus another firm's store whose data must
    never show up."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.arusha = Store.objects.create(entity=self.entity, name='Arusha')
        self.babati = Store.objects.create(entity=self.entity, name='Babati')
        other = Entity.objects.create(name='Firm B')
        self.other_store = Store.objects.create(entity=other, name='Elsewhere')

        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Piece', unit_value=1)
        self.drinks = Category.objects.create(entity=self.entity, name='Beverages')
        self.soda = Product.objects.create(entity=self.entity, name='Soda', uom=uom, category=self.drinks)
        self.soap = Product.objects.create(entity=self.entity, name='Soap', uom=uom)
        self.cash, _ = PaymentMethod.objects.get_or_create(
            implementation=PaymentMethod.Implementation.CASH, defaults={'name': 'Cash', 'is_active': True})
        self.customer = Customer.objects.create(entity=self.entity, name='Mama Neema')

        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity,
                                              first_name='Asha', last_name='Juma')
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)

        self.batches = {}
        # Arusha: Soda Sep 1000 (cost 600), Oct 2000 (cost 1200) + Soap Oct 500 (cost 100)
        # Babati: Soda Oct 4000 (cost 2400). Another firm: 99999 in Oct.
        self.sell(self.arusha, [(self.soda, 1, 1000, 600)], at(2026, 9, 3))
        self.sell(self.arusha, [(self.soda, 2, 1000, 600), (self.soap, 1, 500, 100)], at(2026, 10, 2, 9),
                  customer=self.customer)
        self.sell(self.babati, [(self.soda, 4, 1000, 600)], at(2026, 10, 9, 18))
        self.sell(self.other_store, [(self.soda, 1, 99999, 1)], at(2026, 10, 9))
        self.client.force_authenticate(self.admin)

    def batch(self, store, product, cost):
        key = (store.id, product.id)
        if key not in self.batches:
            self.batches[key] = StockBatch.objects.create(
                store=store, product=product, batch_no='B', unit_cost=cost, qty_on_hand=0)
        return self.batches[key]

    def sell(self, store, lines, when, customer=None, credit=0):
        sale = Sale.objects.create(store=store, status=Sale.Status.COMPLETED, completed_at=when,
                                   payment_method=self.cash, cashier=self.admin, customer=customer,
                                   credit_amount=credit)
        for product, qty, price, cost in lines:
            SaleLine.objects.create(sale=sale, batch=self.batch(store, product, cost), qty=qty,
                                    unit_price=price, vat_class='standard')
        return sale

    def query(self, *dimensions, filters=(), totals=(), expect=status.HTTP_200_OK):
        params = {'dimension': list(dimensions), 'filter': list(filters), 'total': list(totals)}
        response = self.client.get('/api/analytics/query/', params)
        self.assertEqual(response.status_code, expect, getattr(response, 'data', None))
        return response.data

    def cells(self, data):
        """{(meta items...): value}"""
        return {tuple(row[:-1]): row[-1] for row in data['rows']}


class QueryTests(QueryFixture):
    def test_net_sales_by_store_and_month_excludes_other_firms(self):
        a, b = str(self.arusha.id), str(self.babati.id)
        data = self.query('dx:sales.net', f'ou:{a};{b}', 'pe:202609;202610')
        self.assertEqual(self.cells(data), {
            ('sales.net', a, '202609'): 1000,
            ('sales.net', a, '202610'): 2500,
            ('sales.net', b, '202610'): 4000,
        })
        self.assertEqual(data['metaData']['items']['ou']['items'][a]['name'], 'Arusha')
        self.assertEqual(data['metaData']['items']['pe']['items']['202610']['name'], 'October 2026')

    def test_totals_are_recomputed_not_summed(self):
        a, b = str(self.arusha.id), str(self.babati.id)
        data = self.query('dx:profit.margin', f'ou:{a};{b}', 'pe:2026', totals=['ou'])
        cells = self.cells(data)
        # Arusha: (3500 - 1900) / 3500; Babati: (4000 - 2400) / 4000.
        self.assertAlmostEqual(cells[('profit.margin', a, '2026')], 45.71, places=2)
        self.assertAlmostEqual(cells[('profit.margin', b, '2026')], 40.0, places=2)
        # Both stores: 3200 / 7500 — not the 85.71 or 42.86 that summing or
        # averaging the cells would give.
        self.assertAlmostEqual(cells[('profit.margin', '__total', '2026')], 42.67, places=2)
        self.assertEqual(data['metaData']['items']['ou']['items']['__total']['name'], 'Total')

    def test_average_sale_value_is_weighted_by_sales(self):
        data = self.query('dx:sales.avg_sale;sales.count', filters=['ou:FIRM', 'pe:2026'])
        # Three sales worth 7500 together.
        self.assertEqual(self.cells(data), {('sales.avg_sale',): 2500, ('sales.count',): 3})

    def test_firm_node_and_period_types_side_by_side(self):
        data = self.query('dx:sales.net', 'pe:2026Q4;202610;20261009', filters=['ou:FIRM'])
        self.assertEqual(self.cells(data), {
            ('sales.net', '2026Q4'): 6500, ('sales.net', '202610'): 6500, ('sales.net', '20261009'): 4000,
        })

    def test_dynamic_dimension_breaks_down_every_value_with_blank_label(self):
        data = self.query('dx:sales.net', 'customer:', 'pe:2026', filters=['ou:FIRM'])
        cells = self.cells(data)
        self.assertEqual(cells[('sales.net', str(self.customer.id), '2026')], 2500)
        self.assertEqual(cells[('sales.net', '', '2026')], 5000)
        names = data['metaData']['items']['customer']['items']
        self.assertEqual(names[str(self.customer.id)]['name'], 'Mama Neema')
        self.assertEqual(names['']['name'], 'Walk-in (not registered)')

    def test_lazy_dimension_items_are_named_and_filterable(self):
        data = self.query('dx:sales.qty', 'product:', filters=['pe:2026', f'category:{self.drinks.id}'])
        self.assertEqual(self.cells(data), {('sales.qty', str(self.soda.id)): 7})
        self.assertEqual(data['metaData']['items']['product']['items'][str(self.soda.id)]['name'], 'Soda')
        data = self.query('dx:sales.net', 'category:', filters=['pe:2026'])
        self.assertEqual(self.cells(data), {('sales.net', str(self.drinks.id)): 7000, ('sales.net', ''): 500})

    def test_hour_of_day_uses_the_shop_timezone(self):
        data = self.query('dx:sales.count', 'hour:9;18', filters=['pe:2026'])
        self.assertEqual(self.cells(data), {('sales.count', '9'): 1, ('sales.count', '18'): 1})

    def test_stock_on_hand_is_a_closing_balance(self):
        batch = self.batch(self.arusha, self.soda, 600)
        for qty, when in ((10, at(2026, 8, 20)), (-3, at(2026, 9, 5)), (5, at(2026, 10, 1))):
            entry = StockLedger.objects.create(store=self.arusha, batch=batch, qty_delta=qty,
                                               ledger_type=StockLedger.LedgerType.OPENING_STOCK)
            StockLedger.objects.filter(pk=entry.pk).update(created_at=when)
        data = self.query('dx:stock.on_hand;stock.value', 'pe:202608;202609;202610', filters=['ou:FIRM'])
        cells = self.cells(data)
        self.assertEqual([cells[('stock.on_hand', p)] for p in ('202608', '202609', '202610')], [10, 7, 12])
        self.assertEqual(cells[('stock.value', '202610')], 7200)
        # As a filter, several periods mean "at the end of the last one".
        data = self.query('dx:stock.on_hand', filters=['pe:202608;202609'])
        self.assertEqual(data['rows'], [['stock.on_hand', 7]])


class QueryRulesTests(QueryFixture):
    def test_store_manager_sees_only_their_store(self):
        manager = User.objects.create_user(username='mgr', password='x', entity=self.entity)
        StoreRole.objects.create(user=manager, store=self.babati, role=Role.STORE_MANAGER)
        self.client.force_authenticate(manager)
        data = self.query('dx:sales.net', filters=['ou:FIRM', 'pe:2026'])
        self.assertEqual(data['rows'], [['sales.net', 4000]])
        self.query('dx:sales.net', f'ou:{self.arusha.id}', filters=['pe:2026'], expect=status.HTTP_400_BAD_REQUEST)
        catalogue = self.client.get('/api/analytics/dimensions/').data
        ou = next(d for d in catalogue['dimensions'] if d['id'] == 'ou')
        self.assertEqual(ou['items'][0]['label'], 'All my stores')
        self.assertEqual([s['label'] for s in ou['items'][0]['children']], ['Babati'])

    def test_another_firms_store_is_refused(self):
        self.query('dx:sales.net', f'ou:{self.other_store.id}', filters=['pe:2026'],
                   expect=status.HTTP_400_BAD_REQUEST)

    def test_switched_off_feature_hides_its_metrics(self):
        set_feature('customer_credit', False, entity=self.entity)
        self.query('dx:credit.given', filters=['pe:2026'], expect=status.HTTP_400_BAD_REQUEST)
        catalogue = self.client.get('/api/analytics/dimensions/').data
        dx = next(d for d in catalogue['dimensions'] if d['id'] == 'dx')
        self.assertNotIn('credit.given', {m['id'] for m in dx['items']})
        self.assertIn('sales.net', {m['id'] for m in dx['items']})

    def test_dimension_that_does_not_apply_is_refused(self):
        data = self.query('dx:purchases.value', 'cashier:', filters=['pe:2026'], expect=status.HTTP_400_BAD_REQUEST)
        self.assertEqual(data['code'], 'dimension_not_applicable')

    def test_bad_requests(self):
        self.query('pe:2026', expect=status.HTTP_400_BAD_REQUEST)  # no dx
        self.query('dx:sales.net', expect=status.HTTP_400_BAD_REQUEST)  # no pe
        self.query('dx:sales.net', 'pe:NEXT_YEAR', expect=status.HTTP_400_BAD_REQUEST)
        self.query('dx:sales.net', 'pe:2026', totals=['dx'], expect=status.HTTP_400_BAD_REQUEST)
        self.query('dx:sales.net', 'pe:2026', 'category:not-a-category', expect=status.HTTP_400_BAD_REQUEST)

    def test_too_many_cells(self):
        with self.settings(ANALYTICS_MAX_CELLS=10):
            data = self.query('dx:sales.net', 'pe:LAST_30_DAYS', expect=status.HTTP_400_BAD_REQUEST)
        self.assertEqual(data['code'], 'too_many_cells')

    def test_cashier_is_refused(self):
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.arusha, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        self.assertEqual(self.client.get('/api/analytics/dimensions/').status_code, status.HTTP_403_FORBIDDEN)
        self.query('dx:sales.net', filters=['pe:2026'], expect=status.HTTP_403_FORBIDDEN)

    def test_item_search(self):
        response = self.client.get('/api/analytics/items/', {'dimension': 'product', 'search': 'so'})
        self.assertEqual({i['label'] for i in response.data}, {'Soda', 'Soap'})
        response = self.client.get('/api/analytics/items/', {'dimension': 'product', 'search': 'zzz',
                                                             'ids': str(self.soap.id)})
        self.assertEqual([i['label'] for i in response.data], ['Soap'])
        self.assertEqual(self.client.get('/api/analytics/items/', {'dimension': 'category'}).status_code, 400)
