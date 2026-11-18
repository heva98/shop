from rest_framework import serializers

from core.models import display_name

from .models import ControlledSubstanceEntry


class ControlledSubstanceEntrySerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    unit = serializers.CharField(source='product.uom.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    sale_number = serializers.IntegerField(source='sale.number', read_only=True, default=None)
    dispensed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ControlledSubstanceEntry
        fields = [
            'id', 'store', 'store_name', 'product', 'product_name', 'unit', 'kind', 'qty', 'batch_no',
            'sale', 'sale_number', 'patient_name', 'prescriber_name', 'prescription_ref',
            'dispensed_by', 'dispensed_by_name', 'recorded_at',
        ]
        read_only_fields = fields

    def get_dispensed_by_name(self, entry):
        return display_name(entry.dispensed_by)
