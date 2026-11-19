"""Starter catalogs, one kit per kind of business: the units of measure,
categories and a handful of products a new shop of that kind starts with.
This is reference data (names, sizes, VAT classes), not tenant data: a
shop gets its own copy when it signs up (core.signup) or is registered
(core.platform), and seed_demo builds its demo shop on the general kit.

Every shop gets its kit's units straight away (seed_uoms), so "Add
product" works on day one. The products and categories are optional
(seed_catalog): the owner ticks "Add a few common products" at sign-up.
"""

from catalog.models import Category, GenericDrug, Product, UnitOfMeasure

# A unit's value counts the smallest piece it is made of, so a Dozen (12)
# converts into 12 Pieces and a Strip of 10 into 10 Tablets.
_DUKA_UNITS = [
    ('Piece', 'Single item', 1),
    ('Packet', 'Single packet', 1),
    ('Bottle', 'Single bottle', 1),
    ('Dozen', '12 pieces', 12),
    ('Crate of 24', 'Crate of 24 bottles', 24),
    ('Carton of 12', 'Carton of 12 packets', 12),
    ('Carton of 48', 'Carton of 48 pieces', 48),
    ('Bag', 'Single bag', 1),
    ('Kilogram', 'Sold by weight (kg)', 1),
    ('Litre', 'Sold by volume (L)', 1),
    ('Metre', 'Sold by length (m)', 1),
]

# name, category, brand, size, unit, VAT class, has an expiry date
_DUKA = {
    'units': _DUKA_UNITS,
    'categories': [
        ('Beverages', 'BEV', 'Soft drinks, water, juice'),
        ('Cereals & flour', 'CER', 'Maize flour, rice, wheat flour'),
        ('Cooking essentials', 'COOK', 'Cooking oil, sugar, salt'),
        ('Toiletries', 'TOIL', 'Soap, toothpaste, tissue'),
        ('Household', 'HH', 'Matches, candles, detergent'),
        ('Stationery', 'STAT', 'Exercise books, pens'),
    ],
    'products': [
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
    ],
}

_GROCERY = {
    'units': [
        ('Piece', 'Single item', 1),
        ('Kilogram', 'Sold by weight (kg)', 1),
        ('Bunch', 'A bunch (e.g. bananas, greens)', 1),
        ('Heap', 'A heap (fungu)', 1),
        ('Tray of 30', 'Tray of 30 eggs', 30),
        ('Bag', 'Single bag', 1),
        ('Packet', 'Single packet', 1),
        ('Litre', 'Sold by volume (L)', 1),
        ('Bottle', 'Single bottle', 1),
    ],
    'categories': [
        ('Fruits', 'FRU', 'Bananas, oranges, avocados, mangoes'),
        ('Vegetables', 'VEG', 'Tomatoes, onions, cabbage, greens'),
        ('Grains & pulses', 'GRN', 'Rice, beans, maize'),
        ('Eggs & dairy', 'DAI', 'Eggs, milk'),
    ],
    'products': [
        ('Tomatoes', 'Vegetables', '', '', 'Kilogram', 'exempt', False),
        ('Onions', 'Vegetables', '', '', 'Kilogram', 'exempt', False),
        ('Irish potatoes', 'Vegetables', '', '', 'Kilogram', 'exempt', False),
        ('Cabbage', 'Vegetables', '', '', 'Piece', 'exempt', False),
        ('Spinach (mchicha)', 'Vegetables', '', '', 'Bunch', 'exempt', False),
        ('Bananas', 'Fruits', '', '', 'Bunch', 'exempt', False),
        ('Oranges', 'Fruits', '', '', 'Piece', 'exempt', False),
        ('Avocado', 'Fruits', '', '', 'Piece', 'exempt', False),
        ('Rice', 'Grains & pulses', '', '', 'Kilogram', 'exempt', False),
        ('Beans', 'Grains & pulses', '', '', 'Kilogram', 'exempt', False),
        ('Eggs', 'Eggs & dairy', '', '', 'Piece', 'exempt', True),
        ('Fresh milk 500ml', 'Eggs & dairy', '', '500 ml', 'Packet', 'exempt', True),
    ],
}

_HARDWARE = {
    'units': [
        ('Piece', 'Single item', 1),
        ('Packet', 'Single packet', 1),
        ('Box', 'Single box', 1),
        ('Bag', 'Single bag', 1),
        ('Kilogram', 'Sold by weight (kg)', 1),
        ('Metre', 'Sold by length (m)', 1),
        ('Roll', 'Single roll', 1),
        ('Sheet', 'Single sheet', 1),
        ('Tin', 'Single tin', 1),
        ('Litre', 'Sold by volume (L)', 1),
        ('Pair', 'Two pieces', 2),
    ],
    'categories': [
        ('Building materials', 'BLD', 'Cement, iron sheets, nails, binding wire'),
        ('Plumbing', 'PLB', 'Pipes, taps, fittings'),
        ('Electrical', 'ELE', 'Cable, sockets, bulbs'),
        ('Paint', 'PNT', 'Paint, brushes, thinner'),
        ('Tools', 'TLS', 'Hammers, spades, padlocks'),
    ],
    'products': [
        ('Cement 50kg', 'Building materials', '', '50 kg', 'Bag', 'standard', False),
        ('Iron sheet 28 gauge', 'Building materials', '', '3 m', 'Sheet', 'standard', False),
        ('Nails 3 inch', 'Building materials', '', '3 inch', 'Kilogram', 'standard', False),
        ('Binding wire', 'Building materials', '', '', 'Kilogram', 'standard', False),
        ('PVC pipe 1/2 inch', 'Plumbing', '', '1/2 inch x 6 m', 'Piece', 'standard', False),
        ('Water tap 1/2 inch', 'Plumbing', '', '1/2 inch', 'Piece', 'standard', False),
        ('Electrical cable 2.5mm', 'Electrical', '', '2.5 mm', 'Metre', 'standard', False),
        ('Energy-saver bulb', 'Electrical', '', '', 'Piece', 'standard', False),
        ('Emulsion paint 4L', 'Paint', '', '4 L', 'Tin', 'standard', False),
        ('Claw hammer', 'Tools', '', '', 'Piece', 'standard', False),
        ('Padlock', 'Tools', '', '', 'Piece', 'standard', False),
    ],
}

_AUTOMOTIVE = {
    'units': [
        ('Piece', 'Single item', 1),
        ('Pair', 'Two pieces (e.g. wiper blades)', 2),
        ('Set of 4', 'Set of 4 (e.g. brake pads, spark plugs)', 4),
        ('Kit', 'Full kit (e.g. clutch kit, gasket set)', 1),
        ('Box', 'Single box', 1),
        ('Packet', 'Single packet', 1),
        ('Litre', 'Sold by volume (L)', 1),
        ('Bottle', 'Single bottle', 1),
        ('Jerrycan', 'Jerrycan / gallon (4-5 L)', 1),
        ('Metre', 'Sold by length (m), e.g. hose', 1),
    ],
    'categories': [
        ('Engine parts', 'ENG', 'Gaskets, belts, spark plugs, timing parts'),
        ('Filters', 'FLT', 'Oil, air and fuel filters'),
        ('Brakes & clutch', 'BRK', 'Brake pads, shoes, discs, clutch kits'),
        ('Suspension & steering', 'SUS', 'Shock absorbers, bushes, ball joints, tie rods'),
        ('Electrical', 'ELC', 'Batteries, bulbs, fuses, wiring'),
        ('Oils & fluids', 'OIL', 'Engine oil, gear oil, brake fluid, coolant'),
        ('Tyres & tubes', 'TYR', 'Tyres, tubes, valves'),
        ('Body & accessories', 'ACC', 'Wiper blades, mirrors, mats, covers'),
    ],
    'products': [
        ('Engine oil 15W-40 5L', 'Oils & fluids', '', '5 L', 'Jerrycan', 'standard', False),
        ('Engine oil 20W-50 1L', 'Oils & fluids', '', '1 L', 'Bottle', 'standard', False),
        ('Brake fluid DOT 4 500ml', 'Oils & fluids', '', '500 ml', 'Bottle', 'standard', False),
        ('Coolant 1L', 'Oils & fluids', '', '1 L', 'Bottle', 'standard', False),
        ('Oil filter', 'Filters', '', '', 'Piece', 'standard', False),
        ('Air filter', 'Filters', '', '', 'Piece', 'standard', False),
        ('Fuel filter', 'Filters', '', '', 'Piece', 'standard', False),
        ('Front brake pads', 'Brakes & clutch', '', '', 'Set of 4', 'standard', False),
        ('Clutch kit', 'Brakes & clutch', '', '', 'Kit', 'standard', False),
        ('Spark plug', 'Engine parts', '', '', 'Piece', 'standard', False),
        ('Fan belt', 'Engine parts', '', '', 'Piece', 'standard', False),
        ('Shock absorber', 'Suspension & steering', '', '', 'Piece', 'standard', False),
        ('Car battery 12V 70Ah', 'Electrical', '', '12V 70Ah', 'Piece', 'standard', False),
        ('Headlight bulb H4', 'Electrical', '', 'H4 12V', 'Piece', 'standard', False),
        ('Tyre 195/65 R15', 'Tyres & tubes', '', '195/65 R15', 'Piece', 'standard', False),
        ('Wiper blades', 'Body & accessories', '', '', 'Pair', 'standard', False),
    ],
}

_BAR = {
    'units': [
        ('Bottle', 'Single bottle', 1),
        ('Can', 'Single can', 1),
        ('Crate of 24', 'Crate of 24 bottles', 24),
        ('Crate of 20', 'Crate of 20 bottles', 20),
        ('Carton of 24', 'Carton of 24 cans', 24),
        ('Tot', 'One tot of spirits', 1),
        ('Glass', 'One glass', 1),
        ('Piece', 'Single item', 1),
        ('Packet', 'Single packet', 1),
    ],
    'categories': [
        ('Beer', 'BEER', 'Lager, stout, cider'),
        ('Spirits & wine', 'SPR', 'Spirits, wine'),
        ('Soft drinks & water', 'SOFT', 'Soda, water, energy drinks'),
        ('Snacks', 'SNK', 'Peanuts, crisps'),
    ],
    'products': [
        ('Lager 500ml', 'Beer', '', '500 ml', 'Bottle', 'standard', True),
        ('Lite lager 500ml', 'Beer', '', '500 ml', 'Bottle', 'standard', True),
        ('Stout 500ml', 'Beer', '', '500 ml', 'Bottle', 'standard', True),
        ('Cider 330ml', 'Beer', '', '330 ml', 'Bottle', 'standard', True),
        ('Spirit 750ml', 'Spirits & wine', '', '750 ml', 'Bottle', 'standard', False),
        ('Spirit 200ml', 'Spirits & wine', '', '200 ml', 'Bottle', 'standard', False),
        ('Red wine 750ml', 'Spirits & wine', '', '750 ml', 'Bottle', 'standard', False),
        ('Soda 350ml', 'Soft drinks & water', '', '350 ml', 'Bottle', 'standard', True),
        ('Drinking water 500ml', 'Soft drinks & water', '', '500 ml', 'Bottle', 'standard', True),
        ('Energy drink 250ml', 'Soft drinks & water', '', '250 ml', 'Can', 'standard', True),
        ('Roasted peanuts', 'Snacks', '', '', 'Packet', 'standard', True),
    ],
}

_PHARMACY = {
    'units': [
        ('Tablet', 'Single tablet', 1),
        ('Capsule', 'Single capsule', 1),
        ('Strip of 10', 'Strip of 10 tablets/capsules', 10),
        ('Strip of 6', 'Strip of 6 tablets', 6),
        ('Pack of 24', 'Pack of 24 tablets', 24),
        ('Box of 100', 'Box of 100 tablets/capsules', 100),
        ('Bottle', 'Single bottle (syrup, suspension)', 1),
        ('Tube', 'Single tube (cream, gel, ointment)', 1),
        ('Sachet', 'Single-use sachet', 1),
        ('Vial', 'Single-dose injectable vial', 1),
        ('Ampoule', 'Single ampoule', 1),
        ('Piece', 'Single item', 1),
        ('Box of 50', 'Box of 50 pieces', 50),
    ],
    'categories': [
        ('Medicines', 'MED', 'Tablets, capsules, syrups, injections'),
        ('Medical supplies', 'SUP', 'Thermometers, masks, gloves, dressings'),
    ],
    'products': [
        ('Paracetamol 500mg tablets', 'Medicines', '', '500mg tablet', 'Tablet', 'zero_rated', True),
        ('Ibuprofen 400mg tablets', 'Medicines', '', '400mg tablet', 'Tablet', 'standard', True),
        ('Amoxicillin 500mg capsules', 'Medicines', '', '500mg capsule', 'Capsule', 'zero_rated', True),
        ('Amoxiclav 625mg tablets', 'Medicines', '', '625mg tablet', 'Tablet', 'standard', True),
        ('Metformin 500mg tablets', 'Medicines', '', '500mg tablet', 'Tablet', 'zero_rated', True),
        ('Artemether/Lumefantrine 20/120mg', 'Medicines', '', '20/120mg tablet', 'Tablet', 'zero_rated', True),
        ('Ceftriaxone 1g injection', 'Medicines', '', '1g injection', 'Vial', 'standard', True),
        ('ORS sachet', 'Medicines', '', '', 'Sachet', 'zero_rated', True),
        ('Digital thermometer', 'Medical supplies', '', '', 'Piece', 'standard', False),
        ('Surgical face mask', 'Medical supplies', '', '', 'Piece', 'standard', False),
    ],
    # product: (generic medicine, prescription-only)
    'medicines': {
        'Paracetamol 500mg tablets': ('Paracetamol', False),
        'Ibuprofen 400mg tablets': ('Ibuprofen', False),
        'Amoxicillin 500mg capsules': ('Amoxicillin', True),
        'Amoxiclav 625mg tablets': ('Amoxicillin/Clavulanic acid', True),
        'Metformin 500mg tablets': ('Metformin', True),
        'Artemether/Lumefantrine 20/120mg': ('Artemether/Lumefantrine', False),
        'Ceftriaxone 1g injection': ('Ceftriaxone', True),
        'ORS sachet': ('Oral rehydration salts', False),
    },
}

KITS = {
    'general': _DUKA, 'supermarket': _DUKA, 'wholesale': _DUKA,
    'grocery': _GROCERY, 'hardware': _HARDWARE, 'automotive': _AUTOMOTIVE, 'bar': _BAR,
    'pharmacy': _PHARMACY,
}
# Kinds without a product list of their own still get the everyday units.
_UNITS_ONLY = {'units': _DUKA_UNITS, 'categories': [], 'products': []}


def kit_for(business_type):
    return KITS.get(business_type, _UNITS_ONLY)


def has_starter_products(business_type):
    return bool(kit_for(business_type)['products'])


def seed_uoms(entity):
    """Returns {name: UnitOfMeasure} for `entity`, creating any of its
    kit's units that are missing."""
    uoms = {}
    for name, description, unit_value in kit_for(entity.business_type)['units']:
        uom, _ = UnitOfMeasure.objects.get_or_create(
            entity=entity, name=name, defaults={'description': description, 'unit_value': unit_value},
        )
        uoms[name] = uom
    return uoms


def seed_categories(entity):
    """Returns {name: Category} for `entity`, creating any missing ones."""
    categories = {}
    for name, short_name, description in kit_for(entity.business_type)['categories']:
        category, _ = Category.objects.get_or_create(
            entity=entity, name=name, defaults={'short_name': short_name, 'description': description},
        )
        categories[name] = category
    return categories


def seed_catalog(entity):
    """Seeds the starter catalog of `entity`'s kind of business (idempotent:
    safe to re-run). Returns {name: Product}."""
    kit = kit_for(entity.business_type)
    uoms = seed_uoms(entity)
    categories = seed_categories(entity)
    medicines = kit.get('medicines', {})
    products = {}
    for name, category, brand, size, uom_name, vat_class, tracks_expiry in kit['products']:
        defaults = {
            'category': categories[category], 'brand': brand, 'size': size,
            'vat_class': vat_class, 'uom': uoms[uom_name], 'tracks_expiry': tracks_expiry,
        }
        if name in medicines:
            generic_name, prescription_only = medicines[name]
            defaults['generic_drug'], _ = GenericDrug.objects.get_or_create(entity=entity, name=generic_name)
            defaults['is_prescription_only'] = prescription_only
        product, _ = Product.objects.get_or_create(entity=entity, name=name, defaults=defaults)
        products[name] = product
    return products
