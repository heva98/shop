"""One importer per kind of data a shop brings with it on day one:
products, suppliers, selling prices and opening stock.

Every import is all-or-nothing: rows are validated and applied inside one
transaction, and if any row has an error, or the caller only asked for a
preview, the whole transaction is rolled back. So a preview shows exactly
what a real import would do, and a file with mistakes never half-loads.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from catalog.models import Category, Product, UnitConversionError, UnitOfMeasure, convert_qty
from core.models import Entity
from inventory.models import StockBatch, StockLedger
from pricing.models import Price
from receiving.models import Supplier

from .parsing import CellError, parse_bool, parse_date, parse_decimal

_TWO_PLACES = Decimal('0.01')


@dataclass
class Column:
    name: str
    help: str
    example: str
    required: bool = False
    aliases: tuple = ()


@dataclass
class ImportResult:
    rows: int = 0
    created: int = 0
    updated: int = 0
    errors: list = field(default_factory=list)
    preview: list = field(default_factory=list)
    notes: list = field(default_factory=list)


class Importer:
    key = ''
    title = ''
    description = ''
    columns = []
    needs_store = False

    def __init__(self, *, entity, store=None, user=None):
        self.entity = entity
        self.store = store
        self.user = user

    # -- column access, tolerant of header variations --------------------
    def _aliases(self):
        return {col.name: (col.name,) + col.aliases for col in self.columns}

    def missing_columns(self, headers):
        present = set(headers)
        return [c.name for c in self.columns if c.required and not present.intersection(self._aliases()[c.name])]

    def cell(self, row, name):
        for alias in self._aliases()[name]:
            if row.get(alias):
                return row[alias]
        return ''

    # -- running ----------------------------------------------------------
    def run(self, rows, *, commit):
        result = ImportResult(rows=len(rows))
        with transaction.atomic():
            for number, row in rows:
                try:
                    with transaction.atomic():
                        outcome, summary = self.import_row(row)
                except (CellError, UnitConversionError) as e:
                    result.errors.append({'row': number, 'message': str(e)})
                    continue
                if outcome == 'created':
                    result.created += 1
                elif outcome == 'updated':
                    result.updated += 1
                if len(result.preview) < 50:
                    result.preview.append({'row': number, 'action': outcome, **summary})
            if result.errors or not commit:
                transaction.set_rollback(True)
        return result

    def import_row(self, row):
        raise NotImplementedError

    # -- shared lookups -------------------------------------------------------
    def find_product(self, text, *, field_name='Product'):
        """A product cell may hold a barcode, a product name, or
        "name size"; it must match exactly one product."""
        text = text.strip()
        if not text:
            raise CellError(f'{field_name} is required.')
        products = Product.objects.filter(entity=self.entity).select_related('uom')
        by_barcode = products.filter(barcode=text).first()
        if by_barcode:
            return by_barcode
        matches = list(products.filter(name__iexact=text))
        if not matches:
            matches = [p for p in products.filter(name__istartswith=text.split(' ')[0])
                       if f'{p.name} {p.size}'.strip().lower() == text.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CellError(f'"{text}" matches {len(matches)} products. Use the barcode or the full name with size.')
        raise CellError(f'No product "{text}". Import products first, or check the spelling.')

    def find_unit(self, text, *, field_name='Unit'):
        unit = UnitOfMeasure.objects.filter(entity=self.entity, name__iexact=text.strip()).first()
        if unit is None:
            raise CellError(f'No unit "{text}". Add it under Settings > Units of measure first.')
        return unit

    def price_store(self):
        return self.store if self.entity.price_mode == Entity.PriceMode.STORE else None


class ProductImporter(Importer):
    key = 'products'
    title = 'Products'
    description = ('Your product list. Existing products (same barcode, or same name and size) are updated; '
                   'new ones are added. Units and categories that don\'t exist yet are created.')
    columns = [
        Column('name', 'Product name as it should appear on receipts.', 'Sugar 1kg', required=True,
               aliases=('product', 'product_name', 'item', 'description')),
        Column('unit', 'The smallest unit you stock and sell (Piece, Packet, Bottle...).', 'Packet',
               required=True, aliases=('uom', 'unit_of_measure')),
        Column('unit_size', 'Only for new units: how many pieces it holds. Default 1.', '1'),
        Column('category', 'Category, e.g. Beverages, Toiletries.', 'Cooking essentials', aliases=('group', 'department')),
        Column('brand', 'Brand or maker.', 'Kilombero', aliases=('make', 'manufacturer')),
        Column('size', 'Pack size, e.g. 500 ml, 2 kg.', '1 kg', aliases=('pack_size', 'weight', 'volume')),
        Column('vat', '"exempt", "zero" or "standard" (18%). Default standard.', 'standard', aliases=('vat_class',)),
        Column('perishable', 'yes / no: does it have an expiry date? Default no.', 'yes',
               aliases=('expires', 'tracks_expiry', 'has_expiry')),
        Column('barcode', 'Barcode printed on the pack.', '6001234567890', aliases=('ean', 'code')),
        Column('selling_price', 'Price per unit, VAT included. Optional.', '3200', aliases=('price',)),
    ]
    _VAT = {'exempt': Product.VatClass.EXEMPT, 'zero': Product.VatClass.ZERO_RATED,
            'zero_rated': Product.VatClass.ZERO_RATED, 'zero-rated': Product.VatClass.ZERO_RATED,
            'standard': Product.VatClass.STANDARD, '18': Product.VatClass.STANDARD, '18%': Product.VatClass.STANDARD}

    def import_row(self, row):
        name = self.cell(row, 'name')
        if not name:
            raise CellError('Name is required.')
        unit_name = self.cell(row, 'unit')
        if not unit_name:
            raise CellError('Unit is required.')
        size = self.cell(row, 'size')
        barcode = self.cell(row, 'barcode')
        vat_text = self.cell(row, 'vat').lower()
        if vat_text and vat_text not in self._VAT:
            raise CellError(f'VAT "{vat_text}" must be exempt, zero or standard.')
        price = parse_decimal(self.cell(row, 'selling_price'), field='Selling price', minimum=0)
        if price is not None and self.entity.price_mode == Entity.PriceMode.STORE and self.store is None:
            raise CellError('Your shop prices each store separately: choose a store to import prices into.')

        unit = UnitOfMeasure.objects.filter(entity=self.entity, name__iexact=unit_name).first()
        if unit is None:
            unit_size = parse_decimal(self.cell(row, 'unit_size'), field='Unit size', minimum=Decimal('0.01')) or 1
            unit = UnitOfMeasure.objects.create(entity=self.entity, name=unit_name, unit_value=unit_size)

        category = None
        category_name = self.cell(row, 'category')
        if category_name:
            category = Category.objects.filter(entity=self.entity, name__iexact=category_name).first() \
                or Category.objects.create(entity=self.entity, name=category_name)

        existing = None
        if barcode:
            existing = Product.objects.filter(entity=self.entity, barcode=barcode).first()
        if existing is None:
            existing = Product.objects.filter(entity=self.entity, name__iexact=name, size__iexact=size).first()
        product = existing or Product(entity=self.entity)
        product.name = name
        product.size = size or product.size
        product.uom = unit
        product.vat_class = self._VAT.get(vat_text, product.vat_class if existing else Product.VatClass.STANDARD)
        if category is not None:
            product.category = category
        for col in ('brand',):
            if self.cell(row, col):
                setattr(product, col, self.cell(row, col))
        perishable = self.cell(row, 'perishable')
        if perishable or not existing:
            product.tracks_expiry = parse_bool(perishable, field='Perishable')
        if barcode:
            clash = Product.objects.filter(entity=self.entity, barcode=barcode).exclude(pk=product.pk).first()
            if clash:
                raise CellError(f'Barcode {barcode} already belongs to {clash.name}.')
            product.barcode = barcode
        product.save()

        if price is not None:
            Price.objects.update_or_create(
                entity=self.entity, store=self.price_store(), product=product, uom=None,
                defaults={'unit_price': price},
            )
        return ('updated' if existing else 'created'), {
            'name': product.name, 'unit': unit.name, 'price': None if price is None else str(price),
        }


class SupplierImporter(Importer):
    key = 'suppliers'
    title = 'Suppliers'
    description = 'Wholesalers and distributors. A supplier with the same name is updated instead of duplicated.'
    columns = [
        Column('name', 'Supplier name.', 'Bakhresa Group (Azam)', required=True, aliases=('supplier',)),
        Column('phone', 'Phone number.', '+255 22 286 0890', aliases=('tel', 'telephone', 'mobile')),
        Column('email', 'Email address.', 'orders@example.co.tz'),
        Column('location', 'Town or address.', 'Dar es Salaam', aliases=('address', 'town')),
        Column('description', 'Notes.', 'Flour and drinks distributor'),
    ]

    def import_row(self, row):
        name = self.cell(row, 'name')
        if not name:
            raise CellError('Name is required.')
        supplier = Supplier.objects.filter(entity=self.entity, name__iexact=name).first()
        existing = supplier is not None
        supplier = supplier or Supplier(entity=self.entity, name=name)
        for col in ('phone', 'email', 'location', 'description'):
            if self.cell(row, col):
                setattr(supplier, col, self.cell(row, col))
        if supplier.email and '@' not in supplier.email:
            raise CellError(f'Email "{supplier.email}" is not valid.')
        supplier.save()
        return ('updated' if existing else 'created'), {'name': supplier.name}


class PriceImporter(Importer):
    key = 'prices'
    title = 'Selling prices'
    description = ('Shelf prices, VAT included. Leave "unit" empty for the price per product unit, or name another '
                   'unit (e.g. "Crate of 24") to set the price when selling in that unit.')
    columns = [
        Column('product', 'Barcode, product name, or name and size.', 'Sugar 1kg',
               required=True, aliases=('name', 'product_name', 'barcode', 'item')),
        Column('price', 'Price, VAT included.', '3200', required=True, aliases=('selling_price', 'unit_price')),
        Column('unit', 'Optional: the unit this price is for.', '', aliases=('uom',)),
    ]

    def import_row(self, row):
        if self.entity.price_mode == Entity.PriceMode.STORE and self.store is None:
            raise CellError('Your shop prices each store separately: choose a store to import prices into.')
        product = self.find_product(self.cell(row, 'product'))
        price = parse_decimal(self.cell(row, 'price'), field='Price', required=True, minimum=0)
        unit_text = self.cell(row, 'unit')
        unit = self.find_unit(unit_text) if unit_text else None
        if unit is not None and unit.pk == product.uom_id:
            unit = None
        _, created = Price.objects.update_or_create(
            entity=self.entity, store=self.price_store(), product=product, uom=unit,
            defaults={'unit_price': price},
        )
        return ('created' if created else 'updated'), {
            'name': product.name, 'unit': unit.name if unit else product.uom.name, 'price': str(price),
        }


class OpeningStockImporter(Importer):
    key = 'opening_stock'
    title = 'Opening stock'
    description = ('What is on the shelf when you start using the system, into one store. Give the expiry date '
                   'for goods that expire; batch numbers are optional. Each batch can be loaded once; correct '
                   'mistakes afterwards with a stock count.')
    needs_store = True
    columns = [
        Column('product', 'Barcode, product name, or name and size.', 'Sugar 1kg',
               required=True, aliases=('name', 'product_name', 'barcode', 'item')),
        Column('quantity', 'Quantity on the shelf.', '40', required=True, aliases=('qty', 'stock', 'quantity_on_hand')),
        Column('expiry_date', 'Expiry, e.g. 2027-03-31 or 03/2027. Required for perishable goods.', '03/2027',
               aliases=('expiry', 'exp', 'best_before')),
        Column('batch_no', 'Optional: batch / lot number on the pack.', '',
               aliases=('batch', 'lot', 'lot_no', 'batch_number')),
        Column('unit', 'Optional: the unit "quantity" is counted in (e.g. "Carton of 12"). Default: the product\'s unit.',
               '', aliases=('uom',)),
        Column('unit_cost', 'Optional: what you paid per product unit.', '2800', aliases=('cost', 'cost_price', 'buying_price')),
    ]

    def import_row(self, row):
        product = self.find_product(self.cell(row, 'product'))
        batch_no = self.cell(row, 'batch_no')
        expiry = parse_date(self.cell(row, 'expiry_date'), field='Expiry date', required=product.tracks_expiry)
        if expiry is not None and expiry < timezone.localdate():
            raise CellError(f'{product.name} expired on {expiry:%d/%m/%Y}. Do not load expired stock as sellable.')
        qty = parse_decimal(self.cell(row, 'quantity'), field='Quantity', required=True, minimum=Decimal('0.01'))
        unit_text = self.cell(row, 'unit')
        unit = self.find_unit(unit_text) if unit_text else None
        base_qty = convert_qty(qty, unit, product.uom).quantize(_TWO_PLACES)
        cost = parse_decimal(self.cell(row, 'unit_cost'), field='Unit cost', minimum=0) or Decimal('0')
        same = StockBatch.objects.filter(store=self.store, product=product, batch_no__iexact=batch_no)
        if not batch_no:
            same = same.filter(expiry_date=expiry)
        if same.exists():
            what = f'Batch {batch_no} of {product.name}' if batch_no else f'{product.name} stock with this expiry'
            raise CellError(f'{what} is already in {self.store.name}. Use a stock count to correct it.')
        batch = StockBatch.objects.create(
            store=self.store, product=product, batch_no=batch_no, expiry_date=expiry, unit_cost=cost)
        StockLedger.record(
            store=self.store, batch=batch, qty_delta=base_qty,
            ledger_type=StockLedger.LedgerType.OPENING_STOCK, ref_type='import',
        )
        return 'created', {
            'name': product.name, 'batch_no': batch_no, 'expiry_date': expiry.isoformat() if expiry else '',
            'quantity': f'{base_qty} {product.uom.name}',
        }


IMPORTERS = {cls.key: cls for cls in (ProductImporter, SupplierImporter, PriceImporter, OpeningStockImporter)}
