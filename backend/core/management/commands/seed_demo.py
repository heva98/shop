"""Seed a demo Shop ERP dataset — idempotent (get_or_create throughout).
Run after `migrate`:

    python manage.py seed_demo

Dev/demo only — refuses to run when DEBUG=False. A real deployment should
never end up with this command's demo shop or demo logins; create your own
Entity + entity_admin via the Django admin (or the app's own onboarding),
then run `seed_catalog` for just the starter product catalog.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from catalog.seed_data import seed_catalog
from core.models import Entity, ModuleEnablement, ModuleRegistry, Role, Store, StoreRole, User
from credit.models import Customer
from inventory.models import StockBatch, StockLedger, StoreProduct
from payments.models import PaymentMethod
from pricing.models import Price, Promotion
from receiving.models import Supplier

DEMO_PASSWORD = 'shop12345'

STORE_DEFS = [
    ('Branch #001 — Kariakoo', 'Dar es Salaam', True, 'EFD-001'),
    ('Branch #002 — Sinza', 'Dar es Salaam', True, 'EFD-002'),
    ('Branch #003 — Mwanza', 'Mwanza', False, ''),
]
MAIN_STORE = 'Branch #001 — Kariakoo'

SUPPLIER_DEFS = [
    ('Bakhresa Group', 'Flour, drinks and food products', 'Dar es Salaam', 'orders@example.co.tz', '+255 22 286 0001'),
    ('Kilombero Sugar Distributors', 'Sugar wholesaler', 'Morogoro', 'sales@example.co.tz', '+255 23 260 0002'),
    ('Kariakoo Wholesale Traders', 'General goods wholesaler', 'Dar es Salaam', 'info@example.co.tz', '+255 22 218 0003'),
]

# product name -> (reorder level, [(batch_no, days until expiry or None, qty), ...]) at the main store
MAIN_STORE_STOCK = {
    'Soda 500ml': (48, [('', 120, 96)]),
    'Drinking water 1.5L': (24, [('', 300, 60)]),
    'Maize flour 2kg': (20, [('MF2410', 90, 35), ('MF2501', 150, 20)]),
    'Rice 1kg': (20, [('', 200, 12)]),
    'Sugar 1kg': (30, [('', 365, 0)]),
    'Cooking oil 1L': (12, [('CO7781', 20, 18)]),
    'Bar soap 800g': (10, [('', None, 40)]),
    'Toothpaste 100ml': (10, [('TP1102', 400, 25)]),
    'Matchbox': (50, [('', None, 200)]),
    'Exercise book 96pg': (30, [('', None, 150)]),
}
# a little stock at the other branch so Enquiries/Transfers has something to fulfil with
BRANCH_STOCK = {
    'Branch #002 — Sinza': {'Sugar 1kg': ('', 300, 40), 'Cooking oil 1L': ('CO7790', 180, 24)},
}

PRICE_DEFS = {
    'Soda 500ml': Decimal('1000'),
    'Drinking water 1.5L': Decimal('1200'),
    'Maize flour 2kg': Decimal('4200'),
    'Rice 1kg': Decimal('3200'),
    'Sugar 1kg': Decimal('3000'),
    'Cooking oil 1L': Decimal('6500'),
    'Bar soap 800g': Decimal('3500'),
    'Toothpaste 100ml': Decimal('2800'),
    'Matchbox': Decimal('100'),
    'Exercise book 96pg': Decimal('800'),
}
# product, unit name, price: selling in a bigger pack
PACK_PRICE_DEFS = [
    ('Soda 500ml', 'Crate of 24', Decimal('21000')),
    ('Matchbox', 'Dozen', Decimal('1100')),
]

# name, phone, credit limit
CUSTOMER_DEFS = [
    ('Mama Neema', '255712000001', Decimal('50000')),
    ('Baraka Hotel', '255754000002', Decimal('300000')),
    ('Mzee Hamisi', '255765000003', None),
]

# username, first, last, role, email
USER_DEFS = [
    ('cashier1', 'Juma', 'Mwakasege', Role.CASHIER, 'juma.mwakasege@example.co.tz'),
    ('storekeeper1', 'Amina', 'Kassim', Role.STOREKEEPER, 'amina.kassim@example.co.tz'),
    ('manager1', 'Fatuma', 'Ndosi', Role.STORE_MANAGER, 'fatuma.ndosi@example.co.tz'),
    ('admin1', 'Rashid', 'Mnyonge', Role.ENTITY_ADMIN, 'rashid.mnyonge@example.co.tz'),
]


class Command(BaseCommand):
    help = 'Seed a demo Shop ERP dataset (idempotent). Dev/demo only.'

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                'seed_demo refuses to run with DEBUG=False — it creates a demo shop and demo '
                f'logins (password "{DEMO_PASSWORD}" for all of them), which must never exist in a real '
                'deployment. Create your own Entity + entity_admin via the Django admin instead, '
                'then run `seed_catalog --entity "<your shop name>"` for the starter catalog.',
            )
        entity = self._entity()
        stores = self._stores(entity)
        products = seed_catalog(entity)
        self._suppliers(entity)
        self._payment_methods()
        self._stock(stores, products)
        self._pricing(entity, products)
        self._promotions(entity, products)
        self._customers(entity)
        self._module_enablements(entity, stores)
        users = self._users(entity, stores[MAIN_STORE])

        self.stdout.write(self.style.SUCCESS(
            f'Seeded "{entity.name}": {len(stores)} stores, {len(products)} products.',
        ))
        self.stdout.write('Demo logins (username / password):')
        for username, user in users.items():
            role = user.store_roles.first()
            self.stdout.write(f'  {username} / {DEMO_PASSWORD}  ({role.role if role else "?"})')

    def _entity(self):
        entity, _ = Entity.objects.get_or_create(
            name='Kariakoo General Stores',
            defaults={'tin': '100-000-001', 'price_mode': Entity.PriceMode.ENTITY},
        )
        return entity

    def _stores(self, entity):
        stores = {}
        for name, address, is_active, efd_device_id in STORE_DEFS:
            store, _ = Store.objects.get_or_create(entity=entity, name=name)
            store.address, store.is_active, store.efd_device_id = address, is_active, efd_device_id
            store.save()
            stores[name] = store
        return stores

    def _suppliers(self, entity):
        for name, description, location, email, phone in SUPPLIER_DEFS:
            Supplier.objects.get_or_create(
                entity=entity, name=name,
                defaults={'description': description, 'location': location, 'email': email, 'phone': phone},
            )

    def _payment_methods(self):
        defs = [
            ('Cash', PaymentMethod.Implementation.CASH, True),
            ('Mobile money', PaymentMethod.Implementation.MOBILE_MONEY, True),
            ('Bank transfer', PaymentMethod.Implementation.BANK_TRANSFER, False),
        ]
        for name, implementation, is_active in defs:
            PaymentMethod.objects.get_or_create(
                implementation=implementation, defaults={'name': name, 'is_active': is_active},
            )

    def _stock(self, stores, products):
        main_store = stores[MAIN_STORE]
        for product_name, (reorder_level, batches) in MAIN_STORE_STOCK.items():
            product = products[product_name]
            StoreProduct.objects.get_or_create(
                store=main_store, product=product, defaults={'reorder_level': reorder_level},
            )
            for batch_no, days, qty in batches:
                self._ensure_batch(main_store, product, batch_no, days, qty)

        # every product gets a StoreProduct row at every other active store
        # so Settings/Reorder Levels has something to list
        for store_name, store in stores.items():
            if not store.is_active or store_name == main_store.name:
                continue
            for product in products.values():
                StoreProduct.objects.get_or_create(store=store, product=product, defaults={'reorder_level': 10})

        for store_name, batch_defs in BRANCH_STOCK.items():
            store = stores[store_name]
            for product_name, (batch_no, days, qty) in batch_defs.items():
                self._ensure_batch(store, products[product_name], batch_no, days, qty)

    def _ensure_batch(self, store, product, batch_no, days, qty):
        expiry_date = None if days is None else timezone.localdate() + timedelta(days=days)
        batch = StockBatch.objects.filter(store=store, product=product, batch_no=batch_no).first()
        if batch is None:
            batch = StockBatch.objects.create(
                store=store, product=product, batch_no=batch_no, expiry_date=expiry_date, unit_cost=0)
            if qty:
                StockLedger.record(
                    store=store, batch=batch, qty_delta=qty,
                    ledger_type=StockLedger.LedgerType.OPENING_STOCK, ref_type='seed', ref_id='',
                )
        return batch

    def _pricing(self, entity, products):
        for product_name, unit_price in PRICE_DEFS.items():
            Price.objects.get_or_create(
                entity=entity, store=None, product=products[product_name], uom=None,
                defaults={'unit_price': unit_price},
            )
        units = {u.name: u for u in entity.units_of_measure.all()}
        for product_name, unit_name, unit_price in PACK_PRICE_DEFS:
            Price.objects.get_or_create(
                entity=entity, store=None, product=products[product_name], uom=units[unit_name],
                defaults={'unit_price': unit_price},
            )

    def _promotions(self, entity, products):
        today = timezone.localdate()
        Promotion.objects.get_or_create(
            entity=entity, name='Back-to-school offer', product=products['Exercise book 96pg'],
            defaults={'promo_price': Decimal('700'), 'starts_on': today - timedelta(days=3),
                      'ends_on': today + timedelta(days=11)},
        )

    def _customers(self, entity):
        for name, phone, credit_limit in CUSTOMER_DEFS:
            Customer.objects.get_or_create(
                entity=entity, phone=phone, defaults={'name': name, 'credit_limit': credit_limit},
            )

    def _module_enablements(self, entity, stores):
        active_stores = [s for s in stores.values() if s.is_active]
        for module in ModuleRegistry.objects.all():
            if module.scope == ModuleRegistry.Scope.ENTITY:
                ModuleEnablement.objects.get_or_create(
                    module=module, entity=entity, store=None, defaults={'enabled': True},
                )
            else:
                for store in active_stores:
                    ModuleEnablement.objects.get_or_create(
                        module=module, entity=entity, store=store, defaults={'enabled': True},
                    )

    def _users(self, entity, main_store):
        users = {}
        for username, first_name, last_name, role, email in USER_DEFS:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={'first_name': first_name, 'last_name': last_name, 'email': email, 'entity': entity},
            )
            user.first_name, user.last_name, user.email, user.entity = first_name, last_name, email, entity
            user.set_password(DEMO_PASSWORD)
            user.save()
            store = None if role == Role.ENTITY_ADMIN else main_store
            StoreRole.objects.get_or_create(user=user, store=store, role=role)
            users[username] = user
        return users
