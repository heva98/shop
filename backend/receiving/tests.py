from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User

from .models import ReceivingInvoice, Supplier


class SupplierTenantIsolationTests(APITestCase):
    def setUp(self):
        self.entity_a = Entity.objects.create(name='Firm A')
        self.entity_b = Entity.objects.create(name='Firm B')
        self.store_a = Store.objects.create(entity=self.entity_a, name='A')

        self.user_a = User.objects.create_user(username='user_a', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=self.user_a, store=self.store_a, role=Role.STORE_MANAGER)

        self.store_a2 = Store.objects.create(entity=self.entity_a, name='A2')

        self.supplier_a = Supplier.objects.create(entity=self.entity_a, name='Supplier A')
        self.supplier_b = Supplier.objects.create(entity=self.entity_b, name='Supplier B')

    def test_supplier_list_excludes_other_entities(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/receiving/suppliers/')
        names = {row['name'] for row in response.data['results']}
        self.assertEqual(names, {'Supplier A'})

    def test_cannot_create_supplier_for_another_entity(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/receiving/suppliers/', {
            'entity': str(self.entity_b.id), 'name': 'Sneaky Supplier',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_create_invoice_under_another_entitys_store(self):
        other_store = Store.objects.create(
            entity=self.entity_b, name='B store',
        )
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(other_store.id), 'supplier': str(self.supplier_a.id),
            'invoice_number': 'INV-1', 'received_date': '2026-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_cannot_mix_store_and_supplier_from_different_entities(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(self.store_a.id), 'supplier': str(self.supplier_b.id),
            'invoice_number': 'INV-2', 'received_date': '2026-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('supplier', response.data)

    def test_cannot_create_invoice_for_sibling_store_in_same_entity(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(self.store_a2.id), 'supplier': str(self.supplier_a.id),
            'invoice_number': 'INV-3', 'received_date': '2026-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('store', response.data)

    def test_cashier_cannot_create_an_invoice(self):
        """Receiving is storekeeper/store_manager territory (NAV_DEFS in
        appData.js) — a cashier's token should be refused outright, not
        merely fail some later validation."""
        cashier = User.objects.create_user(username='cashier_x', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=cashier, store=self.store_a, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        response = self.client.post('/api/receiving/invoices/', {
            'store': str(self.store_a.id), 'supplier': str(self.supplier_a.id),
            'invoice_number': 'INV-4', 'received_date': '2026-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cashier_cannot_create_a_supplier(self):
        cashier = User.objects.create_user(username='cashier_y', password='x', entity=self.entity_a)
        StoreRole.objects.create(user=cashier, store=self.store_a, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        response = self.client.post('/api/receiving/suppliers/', {
            'entity': str(self.entity_a.id), 'name': 'New Supplier',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ReceivingInvoiceLineAppendTests(APITestCase):
    """Covers the draft-resume path: lines appended one at a time via the
    standalone ReceivingInvoiceLineViewSet, not the invoice's nested create."""

    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='A')
        self.other_store = Store.objects.create(entity=self.entity, name='A2')
        self.manager = User.objects.create_user(username='manager', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.manager, store=self.store, role=Role.STORE_MANAGER)
        self.supplier = Supplier.objects.create(entity=self.entity, name='Supplier A')
        uom = UnitOfMeasure.objects.create(entity=self.entity, name='Strip', unit_value=10)
        self.product = Product.objects.create(entity=self.entity, name='Amoxicillin', uom=uom)
        self.draft = ReceivingInvoice.objects.create(
            store=self.store, supplier=self.supplier, invoice_number='INV-1', received_date='2026-01-01',
        )
        self.other_draft = ReceivingInvoice.objects.create(
            store=self.other_store, supplier=self.supplier, invoice_number='INV-2', received_date='2026-01-01',
        )

    def test_can_append_a_line_to_own_draft(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/receiving/invoice-lines/', {
            'invoice': str(self.draft.id), 'product': str(self.product.id), 'uom': str(self.product.uom_id),
            'order_qty': 10, 'pack_price': 1000, 'batch_no': 'B1', 'expiry_date': '2027-01-01',
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.draft.lines.count(), 1)

    def test_cannot_append_a_line_to_a_store_without_a_role_there(self):
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/receiving/invoice-lines/', {
            'invoice': str(self.other_draft.id), 'product': str(self.product.id), 'uom': str(self.product.uom_id),
            'order_qty': 10, 'pack_price': 1000,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_append_a_line_to_an_already_received_invoice(self):
        self.draft.lines.create(product=self.product, uom=self.product.uom, order_qty=5, pack_price=500, batch_no='B0', expiry_date='2027-01-01')
        self.draft.mark_received()
        self.client.force_authenticate(self.manager)
        response = self.client.post('/api/receiving/invoice-lines/', {
            'invoice': str(self.draft.id), 'product': str(self.product.id), 'uom': str(self.product.uom_id),
            'order_qty': 10, 'pack_price': 1000,
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ReceivingUnitConversionTests(APITestCase):
    """The invoice is in the supplier's pack; stock and cost are held in the
    product's own unit."""

    def setUp(self):
        from inventory.models import StockBatch
        self.StockBatch = StockBatch
        entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=entity, name='A')
        self.supplier = Supplier.objects.create(entity=entity, name='MSD')
        self.tablet = UnitOfMeasure.objects.create(entity=entity, name='Tablet', unit_value=1)
        self.box = UnitOfMeasure.objects.create(entity=entity, name='Box of 100', unit_value=100)
        self.product = Product.objects.create(entity=entity, name='Paracetamol', uom=self.tablet)
        self.invoice = ReceivingInvoice.objects.create(
            store=self.store, supplier=self.supplier, invoice_number='INV-9', received_date='2026-01-01')

    def test_boxes_are_received_as_tablets_with_cost_per_tablet(self):
        self.invoice.lines.create(product=self.product, uom=self.box, order_qty=2, pack_price=15000,
                                  batch_no='P1', expiry_date='2028-01-01')
        self.invoice.mark_received()
        batch = self.StockBatch.objects.get(batch_no='P1')
        self.assertEqual(batch.qty_on_hand, 200)
        self.assertEqual(batch.unit_cost, 150)

    def test_perishable_line_without_expiry_is_refused(self):
        from inventory.models import StockError
        self.product.tracks_expiry = True
        self.product.save()
        self.invoice.lines.create(product=self.product, uom=self.box, order_qty=1, pack_price=1, batch_no='P2')
        with self.assertRaises(StockError):
            self.invoice.mark_received()
        self.assertEqual(self.invoice.status, ReceivingInvoice.Status.DRAFT)

    def test_goods_that_never_expire_need_no_batch_or_expiry(self):
        self.invoice.lines.create(product=self.product, uom=self.box, order_qty=1, pack_price=15000)
        self.invoice.lines.create(product=self.product, uom=self.box, order_qty=2, pack_price=15000)
        self.invoice.mark_received()
        batch = self.StockBatch.objects.get(product=self.product)
        self.assertEqual((batch.batch_no, batch.expiry_date, batch.qty_on_hand), ('', None, 300))
