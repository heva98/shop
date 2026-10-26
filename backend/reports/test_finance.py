from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework import status

from inventory.models import StockBatch
from pos.tests import PosTestBase
from receiving.models import ReceivingInvoice, Supplier


class SupplierPaymentAndPayablesTests(PosTestBase):
    def setUp(self):
        super().setUp()
        today = timezone.localdate()
        self.supplier = Supplier.objects.create(entity=self.entity, name='MSD', payment_terms_days=30)
        self.invoice = ReceivingInvoice.objects.create(
            store=self.store, supplier=self.supplier, invoice_number='INV-1', received_date=today - timedelta(days=45))
        self.invoice.lines.create(product=self.product, uom=self.product.uom, order_qty=10, pack_price=1000,
                                  batch_no='R1', expiry_date=today + timedelta(days=400))
        self.invoice.mark_received()
        self.client.force_authenticate(self.manager)

    def pay(self, amount):
        return self.client.post(f'/api/receiving/invoices/{self.invoice.id}/pay/', {
            'amount': amount, 'paid_on': str(timezone.localdate()), 'method': 'bank', 'reference': 'TRX1'})

    def test_due_date_follows_supplier_terms_and_report_ages_the_debt(self):
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.due_date, self.invoice.received_date + timedelta(days=30))
        report = self.client.get('/api/reports/payables/', {'store': str(self.store.id)}).data
        self.assertEqual(report['summary']['owed'], Decimal('10000.00'))
        self.assertEqual(report['rows'][0]['bucket'], 'overdue_1_30')
        self.assertEqual(report['rows'][0]['days_overdue'], 15)

    def test_payments_reduce_the_balance_and_cannot_overpay(self):
        response = self.pay('4000')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['balance'], '6000.00')
        self.assertEqual(self.pay('7000').status_code, status.HTTP_400_BAD_REQUEST)
        self.pay('6000')
        report = self.client.get('/api/reports/payables/', {'store': str(self.store.id)}).data
        self.assertEqual(report['rows'], [])

    def test_only_managers_record_payments_and_received_invoices_are_locked(self):
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.pay('100').status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(self.manager)
        edit = self.client.patch(f'/api/receiving/invoices/{self.invoice.id}/', {'invoice_number': 'CHANGED'})
        self.assertEqual(edit.status_code, status.HTTP_400_BAD_REQUEST)


class MarginAndMoversTests(PosTestBase):
    def setUp(self):
        super().setUp()
        StockBatch.objects.filter(store=self.store).update(unit_cost=Decimal('600'))
        self.open_shift()
        sale = self.new_sale(qty='5')       # 5 x 1,180 incl. 18% VAT = 5,000 ex VAT; cost 3,000
        self.complete(sale['id'])
        self.client.force_authenticate(self.manager)

    def test_margin_is_on_sales_without_vat_less_batch_cost(self):
        report = self.client.get('/api/reports/margin/', {'store': str(self.store.id)}).data
        self.assertEqual(report['summary']['sales_ex_vat'], Decimal('5000.00'))
        self.assertEqual(report['summary']['cost'], Decimal('3000.00'))
        self.assertEqual(report['summary']['margin'], Decimal('2000.00'))
        self.assertEqual(report['summary']['margin_pct'], 40.0)

    def test_movers_reports_days_of_cover_and_dead_stock(self):
        from catalog.models import Product
        idle = Product.objects.create(entity=self.entity, name='Idle syrup', uom=self.product.uom)
        StockBatch.objects.create(store=self.store, product=idle, batch_no='I1',
                                  expiry_date=timezone.localdate() + timedelta(days=300), qty_on_hand=Decimal('9'))
        report = self.client.get('/api/reports/movers/', {'store': str(self.store.id), 'days': '30'}).data
        rows = {r['product']: r for r in report['rows']}
        self.assertEqual(rows['Paracetamol']['sold'], Decimal('5'))
        self.assertEqual(rows['Paracetamol']['days_of_cover'], 282)  # 47 left / (5/30 per day)
        self.assertEqual(rows['Idle syrup']['class'], 'dead')
