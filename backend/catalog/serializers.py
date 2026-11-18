from django.utils.translation import gettext
from rest_framework import serializers

from core.serializers import validate_owned_entity

from .models import Category, GenericDrug, Product, UnitOfMeasure


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'entity', 'name', 'short_name', 'description']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


class UnitOfMeasureSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ['id', 'entity', 'name', 'description', 'unit_value']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


class GenericDrugSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenericDrug
        fields = ['id', 'entity', 'name', 'short_name', 'description']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


class ProductSerializer(serializers.ModelSerializer):
    uom_name = serializers.CharField(source='uom.name', read_only=True, default='')
    category_name = serializers.CharField(source='category.name', read_only=True, default='')
    generic_drug_name = serializers.CharField(source='generic_drug.name', read_only=True, default='')

    class Meta:
        model = Product
        fields = [
            'id', 'entity', 'category', 'category_name', 'name', 'short_name', 'description', 'brand', 'size',
            'vat_class', 'uom', 'uom_name', 'barcode', 'tracks_expiry', 'generic_drug', 'generic_drug_name',
            'is_prescription_only', 'is_controlled_substance', 'registration_number', 'created_at',
        ]
        # Barcode uniqueness is checked in validate() with a message that
        # names the clashing product, instead of DRF's generic one.
        validators = []

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))

    def validate(self, attrs):
        entity = attrs.get('entity', getattr(self.instance, 'entity', None))
        category = attrs.get('category', getattr(self.instance, 'category', None))
        uom = attrs.get('uom', getattr(self.instance, 'uom', None))
        generic = attrs.get('generic_drug', getattr(self.instance, 'generic_drug', None))
        barcode = (attrs.get('barcode') or '').strip()
        if 'barcode' in attrs:
            attrs['barcode'] = barcode
        if entity is not None and barcode:
            clash = Product.objects.filter(entity=entity, barcode=barcode)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({'barcode': gettext('Barcode {barcode} is already used by {name}.').format(barcode=barcode, name=clash.first().name)})
        if entity is not None:
            if category is not None and category.entity_id != entity.id:
                raise serializers.ValidationError(
                    {'category': gettext('This category is not in your shop.')})
            if uom is not None and uom.entity_id != entity.id:
                raise serializers.ValidationError(
                    {'uom': gettext('This unit is not in your shop.')})
            if generic is not None and generic.entity_id != entity.id:
                raise serializers.ValidationError(
                    {'generic_drug': gettext('This generic medicine is not in your shop.')})
        return attrs
