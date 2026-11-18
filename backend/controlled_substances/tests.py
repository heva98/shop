from decimal import Decimal

from rest_framework import status

from catalog.models import GenericDrug, Product
from core.features import is_enabled, set_feature
from core.models import Entity, Role, StoreRole, User
from inventory.models import StockBatch
from pos.models import Sale
from pos.tests import PosTestBase
from pricing.models import Price

from .models import ControlledSubstanceEntry

RX = {'patient_name': 'Asha Juma', 'prescriber_name': 'Dr. Mrema, Mwananyamala', 'prescription_ref': 'RX-102'}


class PharmacyTillTests(PosTestBase):
    def setUp(self):
        super().setUp()
        Entity.objects.filter(pk=self.entity.pk).update(business_type=Entity.BusinessType.PHARMACY)
        self.entity.refresh_from_db()
        self.pharmacist = User.objects.create_user(username='pharmacist', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.pharmacist, store=self.store, role=Role.STOREKEEPER)
        generic = GenericDrug.objects.create(entity=self.entity, name='Amoxicillin')
        self.pom = Product.objects.create(entity=self.entity, name='Amoxicillin 500mg', uom=self.product.uom,
                                          generic_drug=generic, is_prescription_only=True)
        self.controlled = Product.objects.create(entity=self.entity, name='Pethidine 50mg', uom=self.product.uom,
                                                 is_controlled_substance=True)
        for product in (self.pom, self.controlled):
            Price.objects.create(entity=self.entity, product=product, unit_price=Decimal('1000'))
            StockBatch.objects.create(store=self.store, product=product, batch_no='B1', qty_on_hand=Decimal('20'))

    def test_prescription_details_are_optional(self):
        self.open_shift()
        response = self.complete(self.new_sale(qty='1', product=self.pom)['id'])
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_prescription_details_are_kept(self):
        self.open_shift()
        sale = self.new_sale(qty='2', product=self.pom)
        response = self.complete(sale['id'], **RX)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(Sale.objects.get(pk=sale['id']).prescriber_name, RX['prescriber_name'])
        self.assertFalse(ControlledSubstanceEntry.objects.exists())  # POM, not controlled

    def test_ordinary_sale_needs_nothing_extra(self):
        self.open_shift()
        self.assertEqual(self.complete(self.new_sale(qty='1')['id']).status_code, status.HTTP_200_OK)

    def test_cashier_can_sell_controlled_drugs_and_it_is_registered(self):
        self.open_shift()
        sale = self.new_sale(qty='1', product=self.controlled)
        response = self.complete(sale['id'])
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(ControlledSubstanceEntry.objects.get().dispensed_by, self.cashier)

    def test_pharmacist_sale_goes_into_the_register_and_a_void_comes_back(self):
        self.open_shift(user=self.pharmacist)
        sale = self.new_sale(qty='3', product=self.controlled)
        response = self.complete(sale['id'], **RX)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        entry = ControlledSubstanceEntry.objects.get()
        self.assertEqual((entry.qty, entry.patient_name, entry.prescription_ref, entry.dispensed_by),
                         (Decimal('3'), 'Asha Juma', 'RX-102', self.pharmacist))

        self.client.force_authenticate(self.manager)
        void = self.client.post(f'/api/pos/sales/{sale["id"]}/void/', {'reason': 'Wrong medicine'})
        self.assertEqual(void.status_code, status.HTTP_200_OK, void.data)
        returned = ControlledSubstanceEntry.objects.get(kind=ControlledSubstanceEntry.Kind.RETURNED)
        self.assertEqual(returned.qty, Decimal('-3'))

        register = self.client.get('/api/controlled-substances/entries/', {'store': str(self.store.id)})
        self.assertEqual(register.status_code, status.HTTP_200_OK)
        self.assertEqual(register.data['count'], 2)

    def test_cashiers_cannot_read_the_register(self):
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get('/api/controlled-substances/entries/').status_code, status.HTTP_403_FORBIDDEN)

    def test_register_switched_off_blocks_controlled_drugs(self):
        set_feature('controlled_substances_register', False, entity=self.entity, store=self.store)
        self.open_shift(user=self.pharmacist)
        response = self.client.post('/api/pos/sales/', {
            'store': str(self.store.id), 'items': [{'product': str(self.controlled.id), 'qty': '1'}]}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_offline_sale_keeps_the_prescription(self):
        shift = self.open_shift(user=self.pharmacist)
        payload = {'id': '6f1d0c1e-1111-4a2b-9c3d-000000000001', 'store': str(self.store.id), 'shift': shift,
                   'items': [{'product': str(self.controlled.id), 'qty': '1', 'unit_price': '1000'}],
                   'payment_method': str(self.cash.id), 'amount_tendered': '1000', **RX}
        response = self.client.post('/api/pos/sales/record/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ControlledSubstanceEntry.objects.get().prescriber_name, RX['prescriber_name'])

    def test_till_copy_carries_the_medicine_flags(self):
        snapshot = self.client.get('/api/pos/till/', {'store': str(self.store.id)}).data
        rows = {p['name']: p for p in snapshot['products']}
        self.assertTrue(rows['Amoxicillin 500mg']['prescription_only'])
        self.assertEqual(rows['Amoxicillin 500mg']['generic_name'], 'Amoxicillin')
        self.assertTrue(rows['Pethidine 50mg']['controlled'])


class PharmacyOnlyFeatureTests(PosTestBase):
    def test_register_is_off_for_other_kinds_of_shop(self):
        self.assertFalse(is_enabled('controlled_substances_register', store=self.store))
        Entity.objects.filter(pk=self.entity.pk).update(business_type=Entity.BusinessType.PHARMACY)
        self.assertTrue(is_enabled('controlled_substances_register', store=self.store))
