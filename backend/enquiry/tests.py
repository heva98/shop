from datetime import date, timedelta
from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.features import set_feature
from core.models import Entity, Role, Store, StoreRole, User
from inventory.models import StockBatch, StockLedger
from payments.models import PaymentMethod

from .models import Enquiry, EnquiryLine, Transfer


def _store(entity, name):
    return Store.objects.create(entity=entity, name=name)


def _user(username, entity, store, role):
    user = User.objects.create_user(username=username, password='x', entity=entity)
    StoreRole.objects.create(user=user, store=store, role=role)
    return user


def _batch(store, product, batch_no, qty, *, expiry=None, cost='100'):
    batch = StockBatch.objects.create(
        store=store, product=product, batch_no=batch_no,
        expiry_date=expiry or date.today() + timedelta(days=365), unit_cost=Decimal(cost), qty_on_hand=0,
    )
    if qty:
        StockLedger.record(store=store, batch=batch, qty_delta=qty, ledger_type=StockLedger.LedgerType.OPENING_STOCK)
    return batch


class EnquiryTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.other_entity = Entity.objects.create(name='Firm B')
        self.store_a = _store(self.entity, 'A')
        self.store_a2 = _store(self.entity, 'A2')
        self.store_b = _store(self.other_entity, 'B')
        self.manager_a = _user('manager_a', self.entity, self.store_a, Role.STORE_MANAGER)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=self.entity, name='Amoxicillin', uom=uom)
        self.client.force_authenticate(self.manager_a)

    def _post(self, store, qty=20):
        return self.client.post('/api/enquiry/enquiries/', {
            'requesting_store': str(store.id), 'lines': [{'product': str(self.product.id), 'qty_requested': qty}],
        }, format='json')

    def test_peer_firm_posts_to_the_shared_board(self):
        response = self._post(self.store_a)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['mode'], 'broadcast')
        self.assertIsNone(response.data['target_store'])

    def test_branch_of_a_hub_firm_asks_the_main_store(self):
        """Mode and target come from the firm's set-up, whatever the client sends."""
        self.entity.main_store = self.store_a2
        self.entity.save()
        response = self.client.post('/api/enquiry/enquiries/', {
            'requesting_store': str(self.store_a.id), 'mode': 'broadcast', 'target_store': str(self.store_b.id),
            'lines': [{'product': str(self.product.id), 'qty_requested': 5}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['mode'], 'hub')
        self.assertEqual(response.data['target_store'], self.store_a2.id)

    def test_an_enquiry_needs_a_product(self):
        response = self.client.post('/api/enquiry/enquiries/', {'requesting_store': str(self.store_a.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_ask_on_behalf_of_a_sibling_store(self):
        response = self._post(self.store_a2)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('requesting_store', response.data)

    def test_cannot_ask_on_behalf_of_another_firms_store(self):
        response = self._post(self.store_b)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cashier_cannot_create_an_enquiry(self):
        self.client.force_authenticate(_user('cashier_z', self.entity, self.store_a, Role.CASHIER))
        self.assertEqual(self._post(self.store_a).status_code, status.HTTP_403_FORBIDDEN)

    def test_refused_when_transfers_are_switched_off(self):
        set_feature('transfer', False, entity=self.entity)
        response = self._post(self.store_a)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('switched off', response.data['detail'])

    def test_a_broadcast_enquiry_cannot_be_rejected(self):
        """Rejecting would close it for every store; others may still help."""
        enquiry = Enquiry.objects.create(requesting_store=self.store_a2, mode=Enquiry.Mode.BROADCAST)
        response = self.client.post(f'/api/enquiry/enquiries/{enquiry.id}/reject/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_the_asking_store_can_cancel(self):
        enquiry = Enquiry.objects.create(requesting_store=self.store_a2, mode=Enquiry.Mode.BROADCAST)
        response = self.client.post(f'/api/enquiry/enquiries/{enquiry.id}/cancel/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TransferTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.main = _store(self.entity, 'Main')
        self.branch = _store(self.entity, 'Branch')
        self.main_manager = _user('main_mgr', self.entity, self.main, Role.STORE_MANAGER)
        self.branch_manager = _user('branch_mgr', self.entity, self.branch, Role.STORE_MANAGER)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Tablet', unit_value=1)
        self.product = Product.objects.create(entity=self.entity, name='Amoxicillin', uom=uom)
        self.expired = _batch(self.main, self.product, 'OLD', 50, expiry=date.today() - timedelta(days=1))
        self.soon = _batch(self.main, self.product, 'SOON', 10, expiry=date.today() + timedelta(days=60), cost='100')
        self.later = _batch(self.main, self.product, 'LATER', 100, expiry=date.today() + timedelta(days=400), cost='120')
        self.client.force_authenticate(self.main_manager)

    def _send(self, qty=30, to=None, **extra):
        return self.client.post('/api/enquiry/transfers/', {
            'from_store': str(self.main.id), 'to_store': str((to or self.branch).id),
            'lines': [{'product': str(self.product.id), 'qty': qty}], **extra,
        }, format='json')

    def _qty(self, store):
        return sum(b.qty_on_hand for b in StockBatch.objects.filter(store=store, product=self.product))

    def _receive(self, transfer_id, by=None, **body):
        self.client.force_authenticate(by or self.branch_manager)
        return self.client.post(f'/api/enquiry/transfers/{transfer_id}/confirm_receipt/', body, format='json')

    def test_sending_picks_earliest_expiry_and_never_expired_stock(self):
        response = self._send(30)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['number'], 1)
        self.assertEqual(response.data['status'], 'dispatched')
        sent = {line['batch_no']: Decimal(line['qty']) for line in response.data['lines']}
        self.assertEqual(sent, {'SOON': Decimal('10'), 'LATER': Decimal('20')})
        self.expired.refresh_from_db()
        self.assertEqual(self.expired.qty_on_hand, 50)
        self.assertEqual(self._send(5).data['number'], 2)

    def test_cannot_send_more_than_the_unexpired_stock(self):
        response = self._send(111)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Transfer.objects.exists())

    def test_cannot_send_an_expired_batch_by_name(self):
        response = self.client.post('/api/enquiry/transfers/', {
            'from_store': str(self.main.id), 'to_store': str(self.branch.id),
            'lines': [{'batch': str(self.expired.id), 'qty': 5}],
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.data['detail'])

    def test_cannot_send_to_the_same_store(self):
        self.assertEqual(self._send(5, to=self.main).status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_send_from_a_store_without_a_role_there(self):
        self.client.force_authenticate(self.branch_manager)
        response = self._send(5)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('from_store', response.data)

    def test_cannot_send_to_another_firm(self):
        other = _store(Entity.objects.create(name='Firm B'), 'Elsewhere')
        self.assertEqual(self._send(5, to=other).status_code, status.HTTP_400_BAD_REQUEST)

    def test_cashier_cannot_send(self):
        self.client.force_authenticate(_user('cashier_t', self.entity, self.main, Role.CASHIER))
        self.assertEqual(self._send(5).status_code, status.HTTP_403_FORBIDDEN)

    def test_receiving_in_full_moves_the_stock(self):
        transfer_id = self._send(30).data['id']
        response = self._receive(transfer_id)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'received')
        self.assertEqual(self._qty(self.branch), 30)
        self.assertEqual(response.data['received_by_name'], 'branch_mgr')
        # The receiving batch keeps the sender's batch number, expiry and cost.
        later = StockBatch.objects.get(store=self.branch, batch_no='LATER')
        self.assertEqual((later.qty_on_hand, later.unit_cost), (20, Decimal('120')))

    def test_a_transfer_cannot_be_received_twice(self):
        transfer_id = self._send(30).data['id']
        self._receive(transfer_id)
        response = self._receive(transfer_id)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._qty(self.branch), 30)

    def test_only_the_receiving_store_confirms(self):
        transfer_id = self._send(30).data['id']
        response = self._receive(transfer_id, by=self.main_manager)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_receiving_more_than_was_sent_is_refused(self):
        data = self._send(5).data
        response = self._receive(data['id'], received_qty_by_line={data['lines'][0]['id']: 6})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._qty(self.branch), 0)

    def test_short_delivery_needs_a_note_and_is_flagged(self):
        data = self._send(5).data
        line_id = data['lines'][0]['id']
        self.assertEqual(self._receive(data['id'], received_qty_by_line={line_id: 3}).status_code,
                         status.HTTP_400_BAD_REQUEST)
        response = self._receive(data['id'], received_qty_by_line={line_id: 3}, note='2 missing from the box')
        self.assertEqual(response.data['status'], 'discrepancy')
        self.assertEqual(self._qty(self.branch), 3)

    def _short(self):
        data = self._send(5).data
        self._receive(data['id'], received_qty_by_line={data['lines'][0]['id']: 3}, note='2 missing')
        return data['id']

    def _resolve(self, transfer_id, resolution):
        return self.client.post(f'/api/enquiry/transfers/{transfer_id}/resolve/', {'resolution': resolution}, format='json')

    def test_short_delivery_returned_to_sender(self):
        transfer_id = self._short()
        response = self._resolve(transfer_id, 'return_to_sender')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'received')
        self.assertEqual(self._qty(self.main), 50 + 110 - 3)

    def test_short_delivery_found_later_at_the_receiver(self):
        response = self._resolve(self._short(), 'received_late')
        self.assertEqual(response.data['status'], 'received')
        self.assertEqual(self._qty(self.branch), 5)

    def test_short_delivery_written_off_shows_as_a_loss(self):
        self._resolve(self._short(), 'write_off')
        self.assertEqual(self._qty(self.main), 50 + 110 - 5)
        lost = StockLedger.objects.get(store=self.main, ledger_type=StockLedger.LedgerType.LOST)
        self.assertEqual(lost.qty_delta, -2)
        self.client.force_authenticate(self.main_manager)
        report = self.client.get('/api/reports/losses/', {'store': str(self.main.id)}).data
        self.assertEqual(report['rows'][0]['note'], 'Lost in transit between stores')

    def test_cancelling_puts_the_stock_back(self):
        transfer_id = self._send(30).data['id']
        response = self.client.post(f'/api/enquiry/transfers/{transfer_id}/cancel/', {'reason': 'Wrong store'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'cancelled')
        self.assertEqual(self._qty(self.main), 160)
        self.assertEqual(self._receive(transfer_id).status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_the_sender_can_cancel(self):
        transfer_id = self._send(30).data['id']
        self.client.force_authenticate(self.branch_manager)
        response = self.client.post(f'/api/enquiry/transfers/{transfer_id}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_transfers_have_no_edit_or_delete(self):
        transfer_id = self._send(5).data['id']
        self.assertEqual(self.client.patch(f'/api/enquiry/transfers/{transfer_id}/', {'status': 'received'}).status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(self.client.delete(f'/api/enquiry/transfers/{transfer_id}/').status_code,
                         status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_peer_transfers_are_not_billed(self):
        data = self._send(5).data
        self.assertEqual(data['mode'], 'peer')
        self.assertIsNone(data['amount'])

    def test_hub_branch_is_billed_at_cost_for_what_it_received(self):
        self.entity.main_store = self.main
        self.entity.save()
        data = self._send(30).data  # 10 @ 100 + 20 @ 120
        self.assertEqual((data['mode'], Decimal(data['amount'])), ('hub', Decimal('3400')))
        soon_line = next(line for line in data['lines'] if line['batch_no'] == 'SOON')
        response = self._receive(data['id'], received_qty_by_line={soon_line['id']: 8}, note='2 broken')
        self.assertEqual(Decimal(response.data['amount']), Decimal('3200'))
        self.client.force_authenticate(self.main_manager)
        response = self._resolve(data['id'], 'write_off')
        self.assertEqual(Decimal(response.data['balance']), Decimal('3200'))

    def test_main_store_records_the_branch_payment(self):
        self.entity.main_store = self.main
        self.entity.save()
        transfer_id = self._send(10).data['id']
        cash = PaymentMethod.objects.get(implementation='cash')
        self.client.force_authenticate(self.main_manager)
        self.assertEqual(self.client.post(f'/api/enquiry/transfers/{transfer_id}/pay/', {'payment_method': str(cash.id)})
                         .status_code, status.HTTP_400_BAD_REQUEST)  # not received yet
        self._receive(transfer_id)
        self.client.force_authenticate(self.branch_manager)
        self.assertEqual(self.client.post(f'/api/enquiry/transfers/{transfer_id}/pay/', {'payment_method': str(cash.id)})
                         .status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.main_manager)
        response = self.client.post(f'/api/enquiry/transfers/{transfer_id}/pay/', {'payment_method': str(cash.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(Decimal(response.data['balance']), 0)
        self.assertIsNotNone(response.data['paid_at'])

    def test_goods_that_never_expire_are_sent_after_dated_stock_and_arrive_undated(self):
        undated = StockBatch.objects.create(store=self.main, product=self.product, unit_cost=Decimal('90'))
        StockLedger.record(store=self.main, batch=undated, qty_delta=20, ledger_type=StockLedger.LedgerType.OPENING_STOCK)
        response = self._send(115)  # SOON 10 + LATER 100, then 5 undated
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual([line['batch_no'] for line in response.data['lines']], ['SOON', 'LATER', ''])
        self._receive(response.data['id'])
        received = StockBatch.objects.get(store=self.branch, product=self.product, batch_no='')
        self.assertEqual((received.expiry_date, received.qty_on_hand), (None, 5))

    def test_refused_when_transfers_are_switched_off(self):
        set_feature('transfer', False, entity=self.entity)
        self.assertEqual(self._send(5).status_code, status.HTTP_403_FORBIDDEN)


class EnquiryFulfillTests(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.requesting_store = _store(self.entity, 'Requesting')
        self.fulfilling_store = _store(self.entity, 'Fulfilling')
        self.manager = _user('manager', self.entity, self.fulfilling_store, Role.STORE_MANAGER)
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Strip', unit_value=10)
        self.product = Product.objects.create(entity=self.entity, name='Amoxicillin', uom=uom)
        self.batch = _batch(self.fulfilling_store, self.product, 'B1', 50)
        self.enquiry = Enquiry.objects.create(requesting_store=self.requesting_store, mode=Enquiry.Mode.BROADCAST)
        EnquiryLine.objects.create(enquiry=self.enquiry, product=self.product, qty_requested=20)
        self.client.force_authenticate(self.manager)

    def _fulfill(self, store=None):
        return self.client.post(f'/api/enquiry/enquiries/{self.enquiry.id}/fulfill/', {
            'from_store': str((store or self.fulfilling_store).id),
            'lines': [{'product': str(self.product.id), 'qty': 15}],
        }, format='json')

    def test_fulfill_sends_the_stock_and_closes_the_enquiry(self):
        response = self._fulfill()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['enquiry']['status'], 'fulfilled')
        self.assertEqual(response.data['transfer']['to_store'], self.requesting_store.id)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, 35)

    def test_a_fulfilled_enquiry_cannot_be_fulfilled_again(self):
        self._fulfill()
        self.assertEqual(self._fulfill().status_code, status.HTTP_400_BAD_REQUEST)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.qty_on_hand, 35)

    def test_a_hub_enquiry_is_for_the_main_store_to_fulfil(self):
        main = _store(self.entity, 'Main')
        self.enquiry.mode, self.enquiry.target_store = Enquiry.Mode.HUB, main
        self.enquiry.save()
        response = self._fulfill()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
