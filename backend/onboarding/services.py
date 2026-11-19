"""A new shop's first day: putting a product on sale in one step, and
measuring how far the shop has got. Both span several modules (catalog,
pricing, inventory, pos), which is why they live here and not in the
kernel's catalog app."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from audit.services import Action, Summary, record
from core.models import Entity, Role, User
from inventory.models import StockBatch, StockLedger, StoreProduct
from inventory.stock import record_movement
from pos.models import Sale
from pricing.models import Price


@transaction.atomic
def put_on_sale(*, entity, store, product=None, product_form=None, selling_price=None, buying_price=None,
                quantity=Decimal('0'), expiry=None, reorder_level=None, request=None):
    """Creates the product (from a validated `product_form`) unless an
    existing `product` is given, sets its selling price, the store's
    reorder level and the stock already on the shelf — all together or
    not at all. Returns the product."""
    price_store = store if entity.price_mode == Entity.PriceMode.STORE else None
    if product is None:
        product = product_form.save()
        record(Action.PRODUCT_CREATED, Summary('Product {name} added', name=product.name), request=request, entity=entity)
    if selling_price is not None:
        Price.objects.update_or_create(entity=entity, store=price_store, product=product, uom=None,
                                       defaults={'unit_price': selling_price})
        record(Action.PRICE_SET, Summary('{label}: set to {unit_price:,.0f}', label=product.name, unit_price=selling_price),
               request=request, store=price_store, entity=entity, data={'product': product.name, 'new': selling_price})
    if store is not None:
        store_product, _ = StoreProduct.objects.get_or_create(store=store, product=product)
        if reorder_level is not None:
            store_product.reorder_level = reorder_level
            store_product.save(update_fields=['reorder_level'])
    if quantity > 0:
        batch = StockBatch.objects.create(store=store, product=product, expiry_date=expiry,
                                          unit_cost=buying_price or Decimal('0'))
        record_movement(store=store, batch=batch, qty_delta=quantity,
                           ledger_type=StockLedger.LedgerType.OPENING_STOCK, ref_type='quick_add')
    return product


def progress(entity, stores, products):
    """How far the shop has got: products, which of them cannot be sold
    yet (no price or no stock in `stores`), sales made and staff added."""
    prices = Price.objects.filter(entity=entity, uom__isnull=True)
    if entity.price_mode == Entity.PriceMode.STORE:
        prices = prices.filter(store__in=stores)
    priced = set(prices.values_list('product_id', flat=True))
    on_hand = dict(StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0).values('product_id')
                   .annotate(qty=Sum('qty_on_hand')).values_list('product_id', 'qty'))
    unready = [p for p in products.select_related('uom').order_by('name') if p.id not in priced or p.id not in on_hand]
    return {
        'products': products.count(),
        'without_price': sum(1 for p in unready if p.id not in priced),
        'without_stock': sum(1 for p in unready if p.id not in on_hand),
        'sales': Sale.objects.filter(store__in=stores, status=Sale.Status.COMPLETED).count(),
        'staff': User.objects.filter(entity=entity, is_active=True).exclude(store_roles__role=Role.ENTITY_ADMIN).count(),
        # The first few that cannot be sold yet, to finish from the checklist.
        'unready': [{'id': p.id, 'name': p.name, 'uom_name': p.uom.name, 'tracks_expiry': p.tracks_expiry,
                     'has_price': p.id in priced, 'qty': str(on_hand.get(p.id, 0))} for p in unready[:8]],
    }
