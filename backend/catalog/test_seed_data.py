from django.test import TestCase

from catalog.models import Product, UnitOfMeasure
from catalog.seed_data import KITS, has_starter_products, seed_catalog, seed_uoms
from core.models import Entity


class StarterKitTests(TestCase):
    def test_each_kind_of_business_gets_its_own_units_and_products(self):
        expected = {'bar': ('Tot', 'Lager 500ml'), 'pharmacy': ('Strip of 10', 'Paracetamol 500mg tablets'),
                    'hardware': ('Metre', 'Cement 50kg'), 'grocery': ('Tray of 30', 'Tomatoes'), 'automotive': ('Set of 4', 'Oil filter'),
                    'general': ('Kilogram', 'Sugar 1kg')}
        for kind, (unit, product) in expected.items():
            entity = Entity.objects.create(name=f'A {kind}', business_type=kind)
            self.assertIn(unit, seed_uoms(entity), kind)
            self.assertIn(product, seed_catalog(entity), kind)
            self.assertFalse(Product.objects.filter(entity=entity, name='Sugar 1kg').exists() and kind != 'general')

    def test_kits_are_consistent(self):
        for kind, kit in KITS.items():
            units = {u[0] for u in kit['units']}
            categories = {c[0] for c in kit['categories']}
            for name, category, _brand, _size, uom, vat, _exp in kit['products']:
                self.assertIn(uom, units, f'{kind}: {name}')
                self.assertIn(category, categories, f'{kind}: {name}')
                self.assertIn(vat, ('standard', 'exempt', 'zero_rated'), f'{kind}: {name}')

    def test_other_kinds_get_units_but_no_products(self):
        entity = Entity.objects.create(name='Phones', business_type='electronics')
        self.assertFalse(has_starter_products('electronics'))
        self.assertEqual(seed_catalog(entity), {})
        self.assertTrue(UnitOfMeasure.objects.filter(entity=entity, name='Piece').exists())

    def test_seeding_twice_adds_nothing(self):
        entity = Entity.objects.create(name='Baa', business_type='bar')
        seed_catalog(entity)
        count = Product.objects.filter(entity=entity).count()
        seed_catalog(entity)
        self.assertEqual(Product.objects.filter(entity=entity).count(), count)
