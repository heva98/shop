import io
import zipfile
from datetime import date
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Role, Store, StoreRole, User
from inventory.models import StockBatch, StockLedger
from pricing.models import Price
from receiving.models import Supplier

from .parsing import CellError, parse_date


def csv_file(text, name='data.csv'):
    return SimpleUploadedFile(name, text.encode('utf-8'), content_type='text/csv')


def xlsx_file(rows, name='data.xlsx'):
    """A minimal real .xlsx (inline strings and numbers), as Excel writes it."""
    def cell(ref, value):
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
    sheet_rows = ''.join(
        f'<row r="{r}">' + ''.join(cell(f'{chr(65 + c)}{r}', v) for c, v in enumerate(values)) + '</row>'
        for r, values in enumerate(rows, start=1)
    )
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    rel_ns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="{rel_ns}"><sheets>'
                                      f'<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels',
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                   'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
                   '</Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{ns}"><sheetData>{sheet_rows}</sheetData></worksheet>')
    return SimpleUploadedFile(name, buffer.getvalue())


class ParseDateTests(APITestCase):
    def test_formats_people_type_for_expiry(self):
        self.assertEqual(parse_date('2027-03-15', field='Expiry'), date(2027, 3, 15))
        self.assertEqual(parse_date('15/03/2027', field='Expiry'), date(2027, 3, 15))
        self.assertEqual(parse_date('03/2027', field='Expiry'), date(2027, 3, 31))
        self.assertEqual(parse_date('2/28', field='Expiry'), date(2028, 2, 29))
        self.assertEqual(parse_date('Mar-2027', field='Expiry'), date(2027, 3, 31))
        self.assertEqual(parse_date('46477', field='Expiry'), date(2027, 3, 31))  # Excel day number
        with self.assertRaises(CellError):
            parse_date('soon', field='Expiry')


class ImportTestBase(APITestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name='Firm A')
        self.store = Store.objects.create(entity=self.entity, name='Main')
        self.admin = User.objects.create_user(username='admin', password='x', entity=self.entity)
        StoreRole.objects.create(user=self.admin, store=None, role=Role.ENTITY_ADMIN)
        self.client.force_authenticate(self.admin)

    def post(self, kind, upload, commit=True, store=None):
        data = {'file': upload, 'commit': 'true' if commit else 'false'}
        if store:
            data['store'] = str(store.id)
        return self.client.post(f'/api/imports/{kind}/', data, format='multipart')


class ProductImportTests(ImportTestBase):
    CSV = ('Product Name,Unit,Unit size,Size,Category,VAT,Perishable,Barcode,Selling price\n'
           'Sugar 1kg,Packet,1,1 kg,Cooking essentials,standard,yes,111,3000\n'
           'Matchbox,Piece,,,,"exempt",no,,100\n')

    def test_preview_changes_nothing_and_commit_creates_everything(self):
        preview = self.post('products', csv_file(self.CSV), commit=False)
        self.assertEqual(preview.status_code, status.HTTP_200_OK, preview.data)
        self.assertEqual((preview.data['created'], preview.data['committed']), (2, False))
        self.assertFalse(Product.objects.exists(), 'a preview must roll back')

        done = self.post('products', csv_file(self.CSV))
        self.assertTrue(done.data['committed'], done.data)
        sugar = Product.objects.get(barcode='111')
        self.assertTrue(sugar.tracks_expiry)
        self.assertEqual((sugar.category.name, sugar.size), ('Cooking essentials', '1 kg'))
        self.assertEqual(sugar.uom.name, 'Packet')
        self.assertEqual(Price.objects.get(product=sugar).unit_price, Decimal('3000'))
        matches = Product.objects.get(name='Matchbox')
        self.assertEqual((matches.vat_class, matches.tracks_expiry), (Product.VatClass.EXEMPT, False))

    def test_reimport_updates_instead_of_duplicating(self):
        self.post('products', csv_file(self.CSV))
        again = self.post('products', csv_file(self.CSV.replace(',3000\n', ',3500\n')))
        self.assertEqual((again.data['created'], again.data['updated']), (0, 2))
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(Price.objects.get(product__barcode='111').unit_price, Decimal('3500'))

    def test_one_bad_row_means_nothing_is_imported(self):
        bad = self.CSV + 'Bad,Piece,,,,maybe,no,,10\n'
        response = self.post('products', csv_file(bad))
        self.assertFalse(response.data['committed'])
        self.assertEqual(response.data['errors'], [{'row': 4, 'message': 'VAT "maybe" must be exempt, zero or standard.'}])
        self.assertFalse(Product.objects.exists())

    def test_missing_required_column_is_reported(self):
        response = self.post('products', csv_file('Name,Size\nX,1 kg\n'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('unit', str(response.data['file']))

    def test_xlsx_files_are_read(self):
        upload = xlsx_file([['Name', 'Unit', 'Selling price'], ['Soda 500ml', 'Bottle', 1000]])
        response = self.post('products', upload)
        self.assertTrue(response.data['committed'], response.data)
        self.assertEqual(Price.objects.get(product__name='Soda 500ml').unit_price, Decimal('1000'))

    def test_cashier_cannot_import(self):
        cashier = User.objects.create_user(username='c', password='x', entity=self.entity)
        StoreRole.objects.create(user=cashier, store=self.store, role=Role.CASHIER)
        self.client.force_authenticate(cashier)
        self.assertEqual(self.post('products', csv_file(self.CSV)).status_code, status.HTTP_403_FORBIDDEN)


class OpeningStockImportTests(ImportTestBase):
    def setUp(self):
        super().setUp()
        bottle = UnitOfMeasure.objects.create(entity=self.entity, name='Bottle', unit_value=1)
        UnitOfMeasure.objects.create(entity=self.entity, name='Crate of 24', unit_value=24)
        self.product = Product.objects.create(entity=self.entity, name='Soda 500ml', uom=bottle,
                                              barcode='222', tracks_expiry=True)

    def test_loads_batches_through_the_ledger_converting_units(self):
        upload = csv_file('product,batch_no,expiry_date,quantity,unit,unit_cost\n'
                          '222,P1,03/2030,3,Crate of 24,700\n'
                          'Soda 500ml,P2,2031-01-31,40,,700\n')
        response = self.post('opening_stock', upload, store=self.store)
        self.assertTrue(response.data['committed'], response.data)
        self.assertEqual(StockBatch.objects.get(batch_no='P1').qty_on_hand, Decimal('72'))
        self.assertEqual(StockBatch.objects.get(batch_no='P1').expiry_date, date(2030, 3, 31))
        self.assertEqual(StockLedger.objects.filter(ledger_type=StockLedger.LedgerType.OPENING_STOCK).count(), 2)

    def test_refuses_expired_duplicate_and_unknown_rows(self):
        self.post('opening_stock', csv_file('product,batch_no,expiry_date,quantity\n222,P1,2030-01-01,5\n'), store=self.store)
        response = self.post('opening_stock', csv_file(
            'product,batch_no,expiry_date,quantity\n'
            '222,P1,2030-01-01,5\n'
            '222,OLD,2020-01-01,5\n'
            'Unknown item,X,2030-01-01,5\n'
            '222,P9,,5\n'), store=self.store)
        self.assertEqual([e['row'] for e in response.data['errors']], [2, 3, 4, 5])
        self.assertIn('Expiry date is required', response.data['errors'][3]['message'])
        self.assertEqual(StockBatch.objects.count(), 1)

    def test_goods_that_never_expire_load_without_batch_or_expiry(self):
        piece = UnitOfMeasure.objects.create(entity=self.entity, name='Piece', unit_value=1)
        Product.objects.create(entity=self.entity, name='Matchbox', uom=piece)
        response = self.post('opening_stock', csv_file('product,quantity\nMatchbox,200\n'), store=self.store)
        self.assertTrue(response.data['committed'], response.data)
        batch = StockBatch.objects.get(product__name='Matchbox')
        self.assertEqual((batch.batch_no, batch.expiry_date, batch.qty_on_hand), ('', None, Decimal('200')))

    def test_store_is_required(self):
        response = self.post('opening_stock', csv_file('product,batch_no,expiry_date,quantity\n222,P1,2030-01-01,5\n'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SupplierAndPriceImportTests(ImportTestBase):
    def test_suppliers_upsert_by_name(self):
        Supplier.objects.create(entity=self.entity, name='Bakhresa')
        response = self.post('suppliers', csv_file('name,phone\nbakhresa,0222860890\nKilombero,0222850021\n'))
        self.assertEqual((response.data['created'], response.data['updated']), (1, 1))
        self.assertEqual(Supplier.objects.get(name='Bakhresa').phone, '0222860890')

    def test_prices_per_unit(self):
        bottle = UnitOfMeasure.objects.create(entity=self.entity, name='Bottle', unit_value=1)
        UnitOfMeasure.objects.create(entity=self.entity, name='Crate of 24', unit_value=24)
        Product.objects.create(entity=self.entity, name='Soda', uom=bottle)
        response = self.post('prices', csv_file('product,price,unit\nSoda,1000,\nSoda,21000,Crate of 24\n'))
        self.assertTrue(response.data['committed'], response.data)
        self.assertEqual(Price.objects.get(uom__isnull=True).unit_price, Decimal('1000'))
        self.assertEqual(Price.objects.get(uom__name='Crate of 24').unit_price, Decimal('21000'))

    def test_template_has_headers_and_example(self):
        response = self.client.get('/api/imports/opening_stock/template/')
        lines = response.content.decode('utf-8-sig').splitlines()
        self.assertEqual(lines[0], 'product,quantity,expiry_date,batch_no,unit,unit_cost')
