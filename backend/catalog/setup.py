"""The owner's first day, in two endpoints the dashboard checklist uses:

    POST /api/catalog/quick-add/        one form → product + selling price +
                                        the stock already on the shelf
    GET  /api/catalog/getting-started/  how far the shop has got: products,
                                        prices, stock, first sale, staff

quick-add takes either the fields of a new product or `product` (the id of
one already in the catalogue, e.g. from the starter list) to give it a
price and stock. Everything is saved together or not at all."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from audit.services import Action, Summary, record
from core.models import Entity, Role, Store, User
from core.permissions import roles
from core.queryset_scoping import accessible_store_ids
from inventory.models import StockBatch, StockLedger, StoreProduct
from pos.models import Sale
from pricing.models import Price

from .models import Product
from .serializers import ProductSerializer

money = dict(max_digits=12, decimal_places=2, min_value=Decimal('0'))


class QuickAddSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), required=False, allow_null=True)
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.filter(is_active=True), required=False, allow_null=True)
    # Required for a new product; for an existing one, left out = keep its price.
    selling_price = serializers.DecimalField(**money, required=False, allow_null=True)
    buying_price = serializers.DecimalField(**money, required=False, allow_null=True)
    quantity = serializers.DecimalField(**money, required=False, allow_null=True)
    expiry_date = serializers.DateField(required=False, allow_null=True)
    reorder_level = serializers.DecimalField(**money, required=False, allow_null=True)


def _store_for(request, entity, store):
    """The store stock and per-store settings go to: the one asked for, or
    a single shop's only store."""
    if store is not None:
        ids = accessible_store_ids(request.user)
        if store.entity_id != entity.id or (ids is not None and store.id not in ids):
            raise serializers.ValidationError({'store': gettext('You do not have access to this store.')})
        return store
    return entity.ensure_single_store()


@api_view(['POST'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def quick_add(request):
    entity = request.user.entity
    if entity is None:
        raise serializers.ValidationError(gettext('Your account is not linked to a shop.'))
    form = QuickAddSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    product = data.get('product')
    if product is not None and product.entity_id != entity.id:
        raise serializers.ValidationError({'product': gettext('This product is not in your shop.')})
    product_form = None
    if product is None:
        product_form = ProductSerializer(data={**dict(request.data.items()), 'entity': entity.id}, context={'request': request})
        product_form.is_valid(raise_exception=True)
        if data.get('selling_price') is None:
            raise serializers.ValidationError({'selling_price': gettext('Give the price you sell it at.')})

    store = _store_for(request, entity, data.get('store'))
    quantity = data.get('quantity') or Decimal('0')
    selling_price = data.get('selling_price')
    per_store_price = selling_price is not None and entity.price_mode == Entity.PriceMode.STORE
    price_store = store if entity.price_mode == Entity.PriceMode.STORE else None
    if store is None and (quantity > 0 or per_store_price or data.get('reorder_level') is not None):
        raise serializers.ValidationError({'store': gettext('Choose the store this is for.')})
    tracks_expiry = product.tracks_expiry if product else product_form.validated_data.get('tracks_expiry', False)
    expiry = data.get('expiry_date') if tracks_expiry else None
    if quantity > 0 and tracks_expiry:
        if expiry is None:
            raise serializers.ValidationError({'expiry_date': gettext('Give the expiry date of the stock on the shelf.')})
        if expiry < timezone.localdate():
            raise serializers.ValidationError({'expiry_date': gettext('This stock has already expired. Do not load expired stock as sellable.')})

    with transaction.atomic():
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
            if data.get('reorder_level') is not None:
                store_product.reorder_level = data['reorder_level']
                store_product.save(update_fields=['reorder_level'])
        if quantity > 0:
            batch = StockBatch.objects.create(store=store, product=product, expiry_date=expiry,
                                              unit_cost=data.get('buying_price') or Decimal('0'))
            StockLedger.record(store=store, batch=batch, qty_delta=quantity,
                               ledger_type=StockLedger.LedgerType.OPENING_STOCK, ref_type='quick_add')
    return Response({'product': ProductSerializer(product).data,
                     'selling_price': str(selling_price) if selling_price is not None else None,
                     'quantity': str(quantity), 'store': store.id if store else None}, status=201)


@api_view(['GET'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def getting_started(request):
    """?store=<id> narrows stock and sales to one store (else every store)."""
    entity = request.user.entity
    if entity is None:
        raise serializers.ValidationError(gettext('Your account is not linked to a shop.'))
    stores = entity.stores.filter(is_active=True)
    store_id = request.query_params.get('store')
    if store_id:
        stores = stores.filter(id=store_id)
    products = Product.objects.filter(entity=entity)
    prices = Price.objects.filter(entity=entity, uom__isnull=True)
    if entity.price_mode == Entity.PriceMode.STORE:
        prices = prices.filter(store__in=stores)
    priced = set(prices.values_list('product_id', flat=True))
    on_hand = dict(StockBatch.objects.filter(store__in=stores, qty_on_hand__gt=0).values('product_id')
                   .annotate(qty=Sum('qty_on_hand')).values_list('product_id', 'qty'))
    unready = [p for p in products.select_related('uom').order_by('name') if p.id not in priced or p.id not in on_hand]
    return Response({
        'products': products.count(),
        'without_price': sum(1 for p in unready if p.id not in priced),
        'without_stock': sum(1 for p in unready if p.id not in on_hand),
        'sales': Sale.objects.filter(store__in=stores, status=Sale.Status.COMPLETED).count(),
        'staff': User.objects.filter(entity=entity, is_active=True).exclude(store_roles__role=Role.ENTITY_ADMIN).count(),
        # The first few that cannot be sold yet, to finish from the checklist.
        'unready': [{'id': p.id, 'name': p.name, 'uom_name': p.uom.name, 'tracks_expiry': p.tracks_expiry,
                     'has_price': p.id in priced, 'qty': str(on_hand.get(p.id, 0))} for p in unready[:8]],
    })
