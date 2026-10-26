"""The shared starter catalog for a general retail shop (duka) — units of
measure, categories and product definitions. This is reference data
(names, sizes, VAT classes), not tenant data, so it's meant to be
committed and shared: any new shop onboarding onto this app runs
seed_catalog() for *their own* Entity to get a sensible starting catalog,
without pulling in any demo Users or demo Entity (see
core.management.commands.seed_demo, which is dev/demo-only and seeds those
separately).
"""

from catalog.models import Category, Product, UnitOfMeasure

UOM_DEFS = [
    ('Piece', 'Single item', 1),
    ('Packet', 'Single packet', 1),
    ('Bottle', 'Single bottle', 1),
    ('Dozen', '12 pieces', 12),
    ('Crate of 24', 'Crate of 24 bottles', 24),
    ('Carton of 12', 'Carton of 12 packets', 12),
    ('Carton of 48', 'Carton of 48 pieces', 48),
    ('Bag', 'Single bag', 1),
]

CATEGORY_DEFS = [
    ('Beverages', 'BEV', 'Soft drinks, water, juice'),
    ('Cereals & flour', 'CER', 'Maize flour, rice, wheat flour'),
    ('Cooking essentials', 'COOK', 'Cooking oil, sugar, salt'),
    ('Toiletries', 'TOIL', 'Soap, toothpaste, tissue'),
    ('Household', 'HH', 'Matches, candles, detergent'),
    ('Stationery', 'STAT', 'Exercise books, pens'),
]

# name, category, brand, size, uom name, vat class, tracks expiry
PRODUCT_DEFS = [
    ('Soda 500ml', 'Beverages', 'Coca-Cola', '500 ml', 'Bottle', 'standard', True),
    ('Drinking water 1.5L', 'Beverages', 'Kilimanjaro', '1.5 L', 'Bottle', 'standard', True),
    ('Maize flour 2kg', 'Cereals & flour', 'Azam', '2 kg', 'Packet', 'exempt', True),
    ('Rice 1kg', 'Cereals & flour', '', '1 kg', 'Packet', 'exempt', True),
    ('Sugar 1kg', 'Cooking essentials', 'Kilombero', '1 kg', 'Packet', 'standard', True),
    ('Cooking oil 1L', 'Cooking essentials', 'Korie', '1 L', 'Bottle', 'standard', True),
    ('Bar soap 800g', 'Toiletries', 'Jamaa', '800 g', 'Piece', 'standard', False),
    ('Toothpaste 100ml', 'Toiletries', 'Colgate', '100 ml', 'Piece', 'standard', True),
    ('Matchbox', 'Household', '', '', 'Piece', 'standard', False),
    ('Exercise book 96pg', 'Stationery', '', '96 pages', 'Piece', 'exempt', False),
]


def seed_uoms(entity):
    """Returns {name: UnitOfMeasure} for `entity`, creating any missing ones."""
    uoms = {}
    for name, description, unit_value in UOM_DEFS:
        uom, _ = UnitOfMeasure.objects.get_or_create(
            entity=entity, name=name, defaults={'description': description, 'unit_value': unit_value},
        )
        uoms[name] = uom
    return uoms


def seed_categories(entity):
    """Returns {name: Category} for `entity`, creating any missing ones."""
    categories = {}
    for name, short_name, description in CATEGORY_DEFS:
        category, _ = Category.objects.get_or_create(
            entity=entity, name=name, defaults={'short_name': short_name, 'description': description},
        )
        categories[name] = category
    return categories


def seed_catalog(entity):
    """Seeds the standard category/product catalog for `entity`
    (idempotent — safe to re-run). Returns {name: Product}."""
    uoms = seed_uoms(entity)
    categories = seed_categories(entity)
    products = {}
    for name, category, brand, size, uom_name, vat_class, tracks_expiry in PRODUCT_DEFS:
        product, _ = Product.objects.get_or_create(
            entity=entity, name=name,
            defaults={
                'category': categories[category], 'brand': brand, 'size': size,
                'vat_class': vat_class, 'uom': uoms[uom_name], 'tracks_expiry': tracks_expiry,
            },
        )
        products[name] = product
    return products
