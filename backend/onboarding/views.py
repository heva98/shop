"""The owner's first day, in two endpoints the dashboard checklist uses:

    POST /api/catalog/quick-add/        one form → product + selling price +
                                        the stock already on the shelf
    GET  /api/catalog/getting-started/  how far the shop has got: products,
                                        prices, stock, first sale, staff

quick-add takes either the fields of a new product or `product` (the id of
one already in the catalogue, e.g. from the starter list) to give it a
price and stock. Everything is saved together or not at all
(services.put_on_sale).

The URLs stay under /api/catalog/ (config/urls.py), where the app has
always called them."""

from decimal import Decimal

from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from catalog.models import Product
from catalog.serializers import ProductSerializer
from core.models import Entity, Role, Store
from core.permissions import roles
from core.queryset_scoping import accessible_store_ids

from . import services

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


def _entity(request):
    entity = request.user.entity
    if entity is None:
        raise serializers.ValidationError(gettext('Your account is not linked to a shop.'))
    return entity


@api_view(['POST'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def quick_add(request):
    entity = _entity(request)
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
    if store is None and (quantity > 0 or per_store_price or data.get('reorder_level') is not None):
        raise serializers.ValidationError({'store': gettext('Choose the store this is for.')})
    tracks_expiry = product.tracks_expiry if product else product_form.validated_data.get('tracks_expiry', False)
    expiry = data.get('expiry_date') if tracks_expiry else None
    if quantity > 0 and tracks_expiry:
        if expiry is None:
            raise serializers.ValidationError({'expiry_date': gettext('Give the expiry date of the stock on the shelf.')})
        if expiry < timezone.localdate():
            raise serializers.ValidationError({'expiry_date': gettext('This stock has already expired. Do not load expired stock as sellable.')})

    product = services.put_on_sale(
        entity=entity, store=store, product=product, product_form=product_form, selling_price=selling_price,
        buying_price=data.get('buying_price'), quantity=quantity, expiry=expiry,
        reorder_level=data.get('reorder_level'), request=request,
    )
    return Response({'product': ProductSerializer(product).data,
                     'selling_price': str(selling_price) if selling_price is not None else None,
                     'quantity': str(quantity), 'store': store.id if store else None}, status=201)


@api_view(['GET'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def getting_started(request):
    """?store=<id> narrows stock and sales to one store (else every store)."""
    entity = _entity(request)
    stores = entity.stores.filter(is_active=True)
    store_id = request.query_params.get('store')
    if store_id:
        stores = stores.filter(id=store_id)
    return Response(services.progress(entity, stores, Product.objects.filter(entity=entity)))
