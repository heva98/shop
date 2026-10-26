from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User

from .models import InsufficientStockError, StockBatch, StockLedger, allocate_fefo


class StockBatchTenantIsolationTests(APITestCase):
    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A')
        self.store_1 = Store.objects.create(entity=self.entity_a, name='Store 1')
        self.store_2 = Store.objects.create(entity=self.entity_a, name='Store 2')

        uom = UnitOfMeasure.objects.create(entity=self.entity_a, name='Tablet', unit_value=1)
        self.product = Product.objects.create(
            entity=self.entity_a, name='Paracetamol', uom=uom,
        )
        self.batch_1 = StockBatch.objects.create(
            store=self.store_1, product=self.product, batch_no='B1', expiry_date=date(2030, 1, 1),
        )
        self.batch_2 = StockBatch.objects.create(
            store=self.store_2, product=self.product, batch_no='B2', expiry_date=date(2030, 1, 1),
        )

        self.cashier_store_1 = User.objects.create_user(username='cashier1', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.cashier_store_1, store=self.store_1, role=Role.CASHIER)
        # Cashiers can't create batches at all; store scoping of writes is
        # tested with a storekeeper, who can.
        self.storekeeper_store_1 = User.objects.create_user(username='keeper1', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.storekeeper_store_1, store=self.store_1, role=Role.STOREKEEPER)

        self.entity_admin = User.objects.create_user(username='admin', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.entity_admin, store=None, role=Role.ENTITY_ADMIN)

    def test_store_scoped_cashier_only_sees_their_own_store(self):
        self.client.force_authenticate(self.cashier_store_1)
        response = self.client.get('/api/inventory/batches/')
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {str(self.batch_1.id)})

    def test_entity_admin_sees_every_store_in_their_entity(self):
        self.client.force_authenticate(self.entity_admin)
        response = self.client.get('/api/inventory/batches/')
        ids = {row['id'] for row in response.data['results']}
        self.assertEqual(ids, {str(self.batch_1.id), str(self.batch_2.id)})

    def test_cannot_create_batch_under_another_entitys_store(self):
        other_entity = Entity.objects.create(name='Firm B')
        other_store = Store.objects.create(
            entity=other_entity, name='Other',
        )
        self.client.force_authenticate(self.storekeeper_store_1)
        response = self.client.post('/api/inventory/batches/', {
            'store': str(other_store.id), 'product': str(self.product.id),
            'batch_no': 'SNEAKY', 'expiry_date': '2030-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_cannot_create_batch_for_sibling_store_in_same_entity(self):
        """Same firm isn't enough — a storekeeper at Store 1 has no role at
        Store 2 and shouldn't be able to write records for it."""
        self.client.force_authenticate(self.storekeeper_store_1)
        response = self.client.post('/api/inventory/batches/', {
            'store': str(self.store_2.id), 'product': str(self.product.id),
            'batch_no': 'SNEAKY-SIBLING', 'expiry_date': '2030-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_entity_admin_can_create_batch_for_any_store_in_their_entity(self):
        self.client.force_authenticate(self.entity_admin)
        response = self.client.post('/api/inventory/batches/', {
            'store': str(self.store_2.id), 'product': str(self.product.id),
            'batch_no': 'ADMIN-OK', 'expiry_date': '2030-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


class StockLedgerIntegrityTests(TestCase):
    """StockLedger.record() is the single chokepoint every stock movement
    goes through — these pin down that it can never take a batch negative,
    regardless of which module is calling it."""

    def setUp(self):
        entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=entity, name='Store 1')
        uom = UnitOfMeasure.objects.create(entity=entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=entity, name='Paracetamol', uom=uom)
        self.batch = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='B1',
            expiry_date=date(2030, 1, 1), qty_on_hand=Decimal('10'),
        )

    def test_record_rejects_a_delta_that_would_go_negative(self):
        with self.assertRaises(InsufficientStockError):
            StockLedger.record(
                store=self.store, batch=self.batch, qty_delta=Decimal('-11'),
                ledger_type=StockLedger.LedgerType.SOLD, ref_type='sale', ref_id='x',
            )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('10'))
        self.assertEqual(StockLedger.objects.filter(batch=self.batch).count(), 0)

    def test_record_allows_a_delta_that_exactly_zeroes_the_batch(self):
        StockLedger.record(
            store=self.store, batch=self.batch, qty_delta=Decimal('-10'),
            ledger_type=StockLedger.LedgerType.SOLD, ref_type='sale', ref_id='x',
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('0'))

    def test_record_allows_positive_deltas_without_a_ceiling(self):
        StockLedger.record(
            store=self.store, batch=self.batch, qty_delta=Decimal('500'),
            ledger_type=StockLedger.LedgerType.TRANSFER_IN, ref_type='invoice', ref_id='x',
        )
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('510'))


class FefoAllocationTests(TestCase):
    """allocate_fefo is what makes First-Expired-First-Out real rather
    than just a helper nothing calls."""

    def setUp(self):
        entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=entity, name='Store 1')
        uom = UnitOfMeasure.objects.create(entity=entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=entity, name='Paracetamol', uom=uom)
        self.expires_soon = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='EXPIRES-SOON',
            expiry_date=timezone.localdate() + timedelta(days=7), qty_on_hand=Decimal('5'),
        )
        self.expires_later = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='EXPIRES-LATER',
            expiry_date=date(2030, 1, 1), qty_on_hand=Decimal('100'),
        )

    def test_allocates_from_the_earliest_expiring_batch_first(self):
        plan = allocate_fefo(self.store, self.product, Decimal('3'))
        self.assertEqual(plan, [(self.expires_soon, Decimal('3'))])

    def test_splits_across_batches_when_the_earliest_one_is_not_enough(self):
        plan = allocate_fefo(self.store, self.product, Decimal('8'))
        self.assertEqual(
            [(batch.batch_no, qty) for batch, qty in plan],
            [('EXPIRES-SOON', Decimal('5')), ('EXPIRES-LATER', Decimal('3'))],
        )

    def test_raises_when_total_stock_is_insufficient(self):
        with self.assertRaises(InsufficientStockError):
            allocate_fefo(self.store, self.product, Decimal('1000'))
        # nothing should be touched by a plan that can't be fulfilled
        self.expires_soon.refresh_from_db()
        self.assertEqual(self.expires_soon.qty_on_hand, Decimal('5'))

    def test_never_allocates_expired_stock(self):
        expired = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='EXPIRED',
            expiry_date=timezone.localdate() - timedelta(days=1), qty_on_hand=Decimal('50'),
        )
        plan = allocate_fefo(self.store, self.product, Decimal('3'))
        self.assertNotIn(expired, [batch for batch, _ in plan])
        with self.assertRaises(InsufficientStockError):
            allocate_fefo(self.store, self.product, Decimal('106'))


class StockControlTestBase(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A')
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=self.entity, name='Paracetamol', uom=uom)
        self.batch = StockBatch.objects.create(
            store=self.store, product=self.product, batch_no='B1', expiry_date=date(2030, 1, 1),
            qty_on_hand=Decimal('50'), unit_cost=Decimal('20'))
        self.storekeeper = User.objects.create_user(username='keeper', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.storekeeper, store=self.store, role=Role.STOREKEEPER)
        self.manager = User.objects.create_user(username='mgr', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)


class StockCountTests(StockControlTestBase):
    def start(self):
        self.client.force_authenticate(self.storekeeper)
        response = self.client.post('/api/inventory/stock-counts/', {'store': str(self.store.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def test_blind_count_then_manager_approval_corrects_stock(self):
        count = self.start()
        line = count['lines'][0]
        self.assertIsNone(line['expected_qty'], 'counters must not see the expected quantity')
        url = f'/api/inventory/stock-counts/{count["id"]}'
        self.client.post(f'{url}/save/', [{'id': line['id'], 'counted_qty': '47'}], format='json')
        self.client.post(f'{url}/found/', {
            'product': str(self.product.id), 'batch_no': 'NEW', 'expiry_date': '2031-01-01', 'counted_qty': '10',
        }, format='json')
        submitted = self.client.post(f'{url}/submit/').data
        self.assertEqual(sorted(l['difference'] for l in submitted['lines']), ['-3.00', '10.00'])

        self.assertEqual(self.client.post(f'{url}/approve/').status_code, status.HTTP_403_FORBIDDEN,
                         'a storekeeper cannot approve')
        self.client.force_authenticate(self.manager)
        approved = self.client.post(f'{url}/approve/')
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('47'))
        self.assertEqual(StockBatch.objects.get(batch_no='NEW').qty_on_hand, Decimal('10'))
        self.assertEqual(StockLedger.objects.filter(ledger_type=StockLedger.LedgerType.STOCK_COUNT).count(), 2)
        self.assertEqual(self.client.post(f'{url}/approve/').status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_submit_with_uncounted_lines(self):
        count = self.start()
        response = self.client.post(f'/api/inventory/stock-counts/{count["id"]}/submit/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_one_count_in_progress_per_store(self):
        self.start()
        response = self.client.post('/api/inventory/stock-counts/', {'store': str(self.store.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class StockAdjustmentTests(StockControlTestBase):
    def test_storekeeper_cannot_write_off(self):
        self.client.force_authenticate(self.storekeeper)
        response = self.client.post('/api/inventory/adjustments/', {
            'batch': str(self.batch.id), 'qty_delta': '-2', 'reason': 'damaged'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_write_off_moves_stock_through_the_ledger(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/inventory/adjustments/', {
            'batch': str(self.batch.id), 'qty_delta': '-2', 'reason': 'damaged', 'note': 'Dropped'})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['value_at_cost'], Decimal('-40'))
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('48'))
        self.assertEqual(StockLedger.objects.get(ref_type='stock_adjustment').ledger_type, 'damaged')

    def test_a_loss_cannot_add_stock(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/inventory/adjustments/', {
            'batch': str(self.batch.id), 'qty_delta': '5', 'reason': 'damaged'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_write_off_all_expired(self):
        StockBatch.objects.create(store=self.store, product=self.product, batch_no='OLD',
                                  expiry_date=timezone.localdate() - timedelta(days=3), qty_on_hand=Decimal('7'))
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/inventory/adjustments/write_off_expired/', {'store': str(self.store.id)})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(StockBatch.objects.get(batch_no='OLD').qty_on_hand, 0)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, Decimal('50'), 'unexpired stock untouched')
