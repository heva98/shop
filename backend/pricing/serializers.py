from rest_framework import serializers

from core.models import Entity
from core.queryset_scoping import accessible_store_ids
from core.serializers import validate_owned_entity

from .models import Bundle, Price, Promotion


class PriceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    uom_name = serializers.CharField(source='uom.name', read_only=True, default=None)

    class Meta:
        model = Price
        fields = ['id', 'entity', 'store', 'product', 'product_name', 'uom', 'uom_name', 'unit_price', 'updated_at']
        # Uniqueness per (entity, store, product, unit) is checked in validate().
        validators = []

    def validate(self, attrs):
        entity = attrs.get('entity', getattr(self.instance, 'entity', None))
        store = attrs.get('store', getattr(self.instance, 'store', None))
        request = self.context.get('request')
        is_privileged = request and request.user.is_superuser

        if request and not is_privileged:
            if entity is None or entity.id != request.user.entity_id:
                raise serializers.ValidationError({'entity': 'Must be your own entity.'})

        if entity is not None:
            if entity.price_mode == Entity.PriceMode.STORE:
                if store is None:
                    raise serializers.ValidationError(
                        {'store': 'This entity prices per store — store is required.'})
                if store.entity_id != entity.id:
                    raise serializers.ValidationError({'store': 'Store must belong to the priced entity.'})
                if request and not is_privileged:
                    store_ids = accessible_store_ids(request.user)
                    if store_ids is not None and store.id not in list(store_ids):
                        raise serializers.ValidationError(
                            {'store': 'You do not have access to this store.'})
            elif store is not None:
                raise serializers.ValidationError(
                    {'store': 'This entity uses one shared price list — leave store empty.'})

        product = attrs.get('product', getattr(self.instance, 'product', None))
        uom = attrs.get('uom', getattr(self.instance, 'uom', None))
        if product is not None:
            if entity is not None and product.entity_id != entity.id:
                raise serializers.ValidationError({'product': 'Product must belong to the priced entity.'})
            if uom is not None and uom.pk == product.uom_id:
                uom = None
                if 'uom' in attrs:
                    attrs['uom'] = None
            if uom is not None and uom.entity_id != product.entity_id:
                raise serializers.ValidationError({'uom': 'Unit must belong to the same entity as the product.'})
            clash = Price.objects.filter(entity=entity, store=store, product=product, uom=uom)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError('A price for this product and unit already exists — edit it instead.')
        return attrs


class BundleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bundle
        fields = ['id', 'entity', 'name', 'products', 'price']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


class PromotionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    uom_name = serializers.CharField(source='uom.name', read_only=True, default=None)
    store_name = serializers.CharField(source='store.name', read_only=True, default=None)
    is_running = serializers.BooleanField(read_only=True)
    regular_price = serializers.SerializerMethodField()

    class Meta:
        model = Promotion
        fields = ['id', 'name', 'store', 'store_name', 'product', 'product_name', 'uom', 'uom_name',
                  'promo_price', 'regular_price', 'starts_on', 'ends_on', 'is_active', 'is_running', 'created_at']

    def get_regular_price(self, promotion):
        try:
            return Price.get_price(entity=promotion.entity, product=promotion.product,
                                   store=promotion.store, uom=promotion.uom).unit_price
        except Price.DoesNotExist:
            return None

    def validate(self, attrs):
        request = self.context.get('request')
        entity = getattr(self.instance, 'entity', None) or (request.user.entity if request else None)
        product = attrs.get('product', getattr(self.instance, 'product', None))
        uom = attrs.get('uom', getattr(self.instance, 'uom', None))
        store = attrs.get('store', getattr(self.instance, 'store', None))
        starts_on = attrs.get('starts_on', getattr(self.instance, 'starts_on', None))
        ends_on = attrs.get('ends_on', getattr(self.instance, 'ends_on', None))
        if entity is not None:
            if product is not None and product.entity_id != entity.id:
                raise serializers.ValidationError({'product': 'Not a product in your catalog.'})
            if uom is not None and uom.entity_id != entity.id:
                raise serializers.ValidationError({'uom': 'Not a unit in your catalog.'})
            if store is not None:
                if store.entity_id != entity.id:
                    raise serializers.ValidationError({'store': 'Not one of your stores.'})
                store_ids = accessible_store_ids(request.user) if request else None
                if store_ids is not None and store.id not in list(store_ids):
                    raise serializers.ValidationError({'store': 'You do not have access to this store.'})
        if starts_on and ends_on and ends_on < starts_on:
            raise serializers.ValidationError({'ends_on': 'The promotion must end on or after the day it starts.'})
        if attrs.get('promo_price') is not None and attrs['promo_price'] <= 0:
            raise serializers.ValidationError({'promo_price': 'The promotion price must be more than 0.'})
        return attrs
