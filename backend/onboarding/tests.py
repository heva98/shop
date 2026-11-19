from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User
from inventory.models import StockBatch, StockLedger, StoreProduct
from pricing.models import Price


class QuickAddTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Duka', store_mode='single')
        self.store = self.entity.ensure_single_store()
        self.piece = UnitOfMeasure.objects.create(entity=self.entity, name='Piece', unit_value=1)
        self.owner = User.objects.create_user(username='owner', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.owner, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.owner)

    def add(self, **fields):
        body = {'name': 'Sugar 1kg', 'uom': str(self.piece.id), 'selling_price': '3200', **fields}
        return self.client.post('/api/catalog/quick-add/', body, format='json')

    def test_product_price_and_stock_in_one_go(self):
        response = self.add(buying_price='2800', quantity='40', reorder_level='10', barcode='6201234567890')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        product = Product.objects.get(name='Sugar 1kg')
        self.assertEqual(product.barcode, '6201234567890')
        self.assertEqual(Price.objects.get(product=product, uom=None, store=None).unit_price, Decimal('3200'))
        batch = StockBatch.objects.get(product=product, store=self.store)
        self.assertEqual((batch.qty_on_hand, batch.unit_cost), (Decimal('40'), Decimal('2800')))
        self.assertEqual(StockLedger.objects.get(batch=batch).ledger_type, StockLedger.LedgerType.OPENING_STOCK)
        self.assertEqual(StoreProduct.objects.get(store=self.store, product=product).reorder_level, Decimal('10'))

    def test_without_stock(self):
        self.assertEqual(self.add().status_code, status.HTTP_201_CREATED)
        self.assertFalse(StockBatch.objects.exists())
        self.assertTrue(StoreProduct.objects.filter(store=self.store).exists())

    def test_perishable_stock_needs_a_future_expiry(self):
        self.assertIn('expiry_date', self.add(tracks_expiry=True, quantity='5').data)
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertIn('expiry_date', self.add(tracks_expiry=True, quantity='5', expiry_date=past).data)
        self.assertFalse(Product.objects.exists())  # nothing half-saved
        future = (timezone.localdate() + timedelta(days=90)).isoformat()
        self.assertEqual(self.add(tracks_expiry=True, quantity='5', expiry_date=future).status_code, 201)

    def test_product_errors_save_nothing(self):
        self.assertIn('name', self.add(name='').data)
        self.assertIn('selling_price', self.add(selling_price='').data)
        self.assertIn('selling_price', self.add(selling_price='-1').data)
        self.assertFalse(Product.objects.exists())
        self.assertFalse(Price.objects.exists())

    def test_existing_product_gets_price_and_stock(self):
        product = Product.objects.create(entity=self.entity, name='Soda 500ml', uom=self.piece)
        response = self.client.post('/api/catalog/quick-add/', {'product': str(product.id), 'selling_price': '1000',
                                                                'quantity': '24'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(StockBatch.objects.get(product=product).qty_on_hand, Decimal('24'))
        # Again: the price is replaced, the stock added as another batch.
        self.client.post('/api/catalog/quick-add/', {'product': str(product.id), 'selling_price': '1100', 'quantity': '6'}, format='json')
        self.assertEqual(Price.objects.get(product=product).unit_price, Decimal('1100'))
        self.assertEqual(sum(b.qty_on_hand for b in StockBatch.objects.filter(product=product)), Decimal('30'))

    def test_stock_only_keeps_the_price(self):
        product = Product.objects.create(entity=self.entity, name='Soda 500ml', uom=self.piece)
        Price.objects.create(entity=self.entity, product=product, unit_price=1000)
        response = self.client.post('/api/catalog/quick-add/', {'product': str(product.id), 'quantity': '12'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(Price.objects.get(product=product).unit_price, Decimal('1000'))
        self.assertEqual(StockBatch.objects.get(product=product).qty_on_hand, Decimal('12'))
        self.assertIn('selling_price', self.add(selling_price=None).data)

    def test_other_shops_products_are_off_limits(self):
        other = Entity.objects.create(name='Other')
        theirs = Product.objects.create(entity=other, name='Theirs', uom=UnitOfMeasure.objects.create(entity=other, name='Piece', unit_value=1))
        response = self.client.post('/api/catalog/quick-add/', {'product': str(theirs.id), 'selling_price': '1'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        other_store = Store.objects.create(entity=other, name='Theirs')
        self.assertIn('store', self.add(store=str(other_store.id), quantity='1').data)

    def test_multi_store_shop_must_choose_a_store_for_stock(self):
        Entity.objects.filter(pk=self.entity.pk).update(store_mode='multi')
        self.owner.refresh_from_db()
        self.assertIn('store', self.add(quantity='5').data)
        self.assertEqual(self.add(quantity='5', store=str(self.store.id)).status_code, status.HTTP_201_CREATED)

    def test_only_owners(self):
        cashier = User.objects.create_user(username='cashier', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        self.assertEqual(self.add().status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/catalog/getting-started/').status_code, status.HTTP_403_FORBIDDEN)

    def test_getting_started(self):
        response = self.client.get('/api/catalog/getting-started/')
        self.assertEqual((response.data['products'], response.data['sales'], response.data['staff']), (0, 0, 0))
        Product.objects.create(entity=self.entity, name='Matchbox', uom=self.piece)
        self.add(quantity='10')
        response = self.client.get('/api/catalog/getting-started/', {'store': str(self.store.id)})
        self.assertEqual(response.data['products'], 2)
        self.assertEqual((response.data['without_price'], response.data['without_stock']), (1, 1))
        self.assertEqual([p['name'] for p in response.data['unready']], ['Matchbox'])
