"""What the till needs to keep selling with no connection: the read side
of pos, served by GET /api/pos/till/ (views.TillSnapshotView).

The catalog, this store's prices for today (a running promotion's price
where there is one), sellable stock, payment methods, credit customers
with what they owe, and the caller's open shift. The till refreshes it
whenever it's online and records what it sells against it
(POST /sales/record/).

The catalog (products and units) is most of the payload and changes
rarely, so it carries a `catalog_version`. A till that sends back the
version it holds gets `products` and `units` as null when they are
unchanged, and keeps its own copy. Stock is summed per product and expiry
date: all the till needs to tell what is sellable today, in fewer rows
than one per batch.

Every till asks for this after each sale it records, so the catalog is
built once per change, not once per request: it is cached as JSON under
the shop's CatalogRevision, which any catalog edit moves on. A till whose
copy is current costs one small query for the catalog.

Stock and prices change with every sale, so they are sent in part: every
product falls in one of SYNC_BUCKETS groups (sync_bucket()), and
`sync_state` is a fingerprint of each group's stock and price rows. A till
that sends back the sync_state it holds gets `sync_buckets`, the groups
that changed, and the stock and price rows of those groups only; it
replaces its rows in those groups and keeps the rest. Nothing is kept on
the server, so any server can answer; a till without a valid state gets
everything, with `sync_buckets` null."""

import hashlib
import json
import re

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum
from django.utils import timezone

from catalog.models import CatalogRevision, Product, UnitOfMeasure
from catalog.serializers import UnitOfMeasureSerializer
from core import features
from core.models import Entity
from core.money import money
from credit.models import Customer, with_balances
from inventory.models import StockBatch
from inventory.stock import sellable_batches
from payments.models import PaymentMethod
from payments.serializers import PaymentMethodSerializer
from pricing.models import Price, Promotion

from .models import Shift
from .serializers import ShiftSerializer
from .services import shifts

CATALOG_CACHE_SECONDS = 60 * 60
SYNC_BUCKETS = 128
_SYNC_STATE = re.compile(rf'^[0-9a-f]{{{SYNC_BUCKETS * 8}}}$')
_ROW_BREAK = chr(10)  # between rows in a sync fingerprint


def sync_bucket(product_id):
    """The group a product's rows are fingerprinted in: from the first 8
    hex digits of its id. offline/snapshotMerge.js does the same."""
    return int(str(product_id)[:8], 16) % SYNC_BUCKETS


def changed_rows(stock, prices, held):
    """(stock, prices, sync_state, changed buckets or None): only the
    rows of groups whose fingerprint differs from `held` (the till's
    sync_state), or all of them when `held` isn't a valid state."""
    groups = [([], []) for _ in range(SYNC_BUCKETS)]
    for row in stock:
        groups[sync_bucket(row['product'])][0].append(row)
    for row in sorted(prices, key=lambda r: (r['product'], r['uom'] or '')):
        groups[sync_bucket(row['product'])][1].append(row)
    # Each row's values as plain text: str() of a Decimal or date is
    # exact, and far cheaper than JSON-encoding thousands of rows.
    hashes = [hashlib.sha256(_ROW_BREAK.join('|'.join(map(str, row.values())) for rows in g for row in rows)
                             .encode()).hexdigest()[:8] for g in groups]
    state = ''.join(hashes)
    if not (held and _SYNC_STATE.match(held)):
        return stock, prices, state, None
    changed = [i for i, h in enumerate(hashes) if held[i * 8:i * 8 + 8] != h]
    return ([row for i in changed for row in groups[i][0]],
            [row for i in changed for row in groups[i][1]], state, changed)


def _build_catalog(entity_id):
    """(version, JSON text of [products, units]). The version is a hash
    of the content, so it only changes when the till's copy would."""
    products = [{
        'id': str(p['id']), 'name': p['name'], 'short_name': p['short_name'], 'brand': p['brand'],
        'size': p['size'], 'barcode': p['barcode'], 'category_name': p['category__name'] or '',
        'uom': str(p['uom_id']), 'vat_class': p['vat_class'], 'tracks_expiry': p['tracks_expiry'],
        'generic_name': p['generic_drug__name'] or '',
        'prescription_only': p['is_prescription_only'], 'controlled': p['is_controlled_substance'],
    } for p in Product.objects.filter(entity_id=entity_id).values(
        'id', 'name', 'short_name', 'brand', 'size', 'barcode', 'category__name', 'uom_id', 'vat_class',
        'tracks_expiry', 'generic_drug__name', 'is_prescription_only', 'is_controlled_substance')]
    units = UnitOfMeasureSerializer(UnitOfMeasure.objects.filter(entity_id=entity_id), many=True).data
    payload = json.dumps([products, units], cls=DjangoJSONEncoder, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16], payload


def catalog(entity_id):
    """(version, JSON text), from the cache while the shop's catalog
    revision is unchanged."""
    key = f'till-catalog:{entity_id}:{CatalogRevision.current(entity_id)}'
    hit = cache.get(key)
    if hit is None:
        hit = _build_catalog(entity_id)
        cache.set(key, hit, CATALOG_CACHE_SECONDS)
    return hit


def _prices(store):
    """{(product id, uom id): {unit_price, regular_price, promotion}}."""
    entity = store.entity
    price_store = store if entity.price_mode == Entity.PriceMode.STORE else None
    prices = {(product_id, uom_id): {'unit_price': unit_price, 'regular_price': unit_price, 'promotion': None}
              for product_id, uom_id, unit_price in Price.objects.filter(entity=entity, store=price_store)
              .values_list('product_id', 'uom_id', 'unit_price')}
    # Store-level promotions come first, so they win over firm-wide ones.
    for promo in reversed(list(Promotion.running(store=store))):
        row = prices.setdefault((promo.product_id, promo.uom_id), {'regular_price': None})
        row.update(unit_price=promo.promo_price, promotion=promo.name)
    return prices


def snapshot(store, cashier, *, catalog_held=None, sync_held=None):
    """The till's snapshot for `cashier` at `store` (see the module
    docstring). `catalog_held` / `sync_held` are the catalog_version and
    sync_state the till already has, if any."""
    entity = store.entity
    catalog_version, catalog_json = catalog(entity.pk)
    if catalog_held == catalog_version:
        products = units = None
    else:
        products, units = json.loads(catalog_json)
    stock = (sellable_batches(StockBatch.objects.filter(store=store))
             .values('product_id', 'expiry_date').annotate(qty=Sum('qty_on_hand'))
             .order_by('product_id', 'expiry_date'))
    stock, prices, sync_state, sync_buckets = changed_rows(
        [{'product': str(row['product_id']), 'qty_on_hand': money(row['qty']), 'expiry_date': row['expiry_date']}
         for row in stock],
        [{'product': str(product), 'uom': str(uom) if uom else None, **row}
         for (product, uom), row in _prices(store).items()],
        sync_held)
    shift = Shift.open_for(store=store, cashier=cashier).first()
    customers = (with_balances(Customer.objects.filter(entity=entity, is_active=True))
                 if features.is_enabled('customer_credit', store=store) else Customer.objects.none())
    shift_data = None
    if shift is not None:
        shift_data = {**ShiftSerializer(shift).data, 'summary': shifts.summary(shift)}
    return {
        'store': str(store.pk),
        'store_details': {'id': str(store.pk), 'name': store.name, 'address': store.address, 'tin': store.tin},
        'generated_at': timezone.now(),
        'cashier_discount_limit': entity.cashier_discount_limit,
        'catalog_version': catalog_version,
        'products': products,
        'units': units,
        'prices': prices,
        'stock': stock,
        'sync_state': sync_state,
        'sync_buckets': sync_buckets,
        'payment_methods': PaymentMethodSerializer(PaymentMethod.active_for(entity), many=True,
                                                   context={'entity': entity}).data,
        'customers': [{'id': str(c.pk), 'name': c.name, 'phone': c.phone, 'owing': c.owing,
                       'credit_limit': c.credit_limit} for c in customers],
        'shift': shift_data,
    }
