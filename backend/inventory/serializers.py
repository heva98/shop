from rest_framework import serializers

from catalog.models import Product
from core.serializers import ClientGeneratedIdMixin, validate_accessible_store

from .models import StockAdjustment, StockBatch, StockCount, StockCountLine, StockLedger, StoreProduct


class StoreProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreProduct
        fields = ['id', 'store', 'product', 'enabled', 'reorder_level']

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))


class StockBatchSerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    unit_name = serializers.CharField(source='product.uom.name', read_only=True)

    class Meta:
        model = StockBatch
        fields = [
            'id', 'store', 'product', 'product_name', 'unit_name', 'batch_no', 'expiry_date',
            'qty_on_hand', 'unit_cost', 'created_at',
        ]
        read_only_fields = ['qty_on_hand']

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))


class StockLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = StockLedger
        fields = ['id', 'store', 'batch', 'qty_delta', 'ledger_type', 'ref_type', 'ref_id', 'created_at']
        read_only_fields = fields


def _name(user):
    return (user.get_full_name() or user.username) if user else ''


class StockAdjustmentSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='batch.product.name', read_only=True)
    batch_no = serializers.CharField(source='batch.batch_no', read_only=True)
    reason_label = serializers.CharField(source='get_reason_display', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    value_at_cost = serializers.SerializerMethodField()

    class Meta:
        model = StockAdjustment
        fields = ['id', 'store', 'batch', 'batch_no', 'product_name', 'qty_delta', 'reason', 'reason_label',
                  'note', 'created_by_name', 'created_at', 'value_at_cost']
        read_only_fields = ['store']

    def get_created_by_name(self, obj):
        return _name(obj.created_by)

    def get_value_at_cost(self, obj):
        return obj.qty_delta * obj.batch.unit_cost

    def validate_batch(self, batch):
        validate_accessible_store(batch.store, self.context.get('request'))
        return batch


class StockCountLineSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    unit_name = serializers.CharField(source='product.uom.name', read_only=True)
    difference = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    unit_cost = serializers.DecimalField(source='batch.unit_cost', max_digits=12, decimal_places=2,
                                         read_only=True, default=0)

    class Meta:
        model = StockCountLine
        fields = ['id', 'batch', 'product', 'product_name', 'unit_name', 'batch_no', 'expiry_date',
                  'expected_qty', 'counted_qty', 'difference', 'adjustment_qty', 'unit_cost']
        read_only_fields = fields

    def to_representation(self, line):
        data = super().to_representation(line)
        # Blind count: nobody sees the system's figures while counting.
        if line.count.status == StockCount.Status.DRAFT:
            data['expected_qty'] = data['difference'] = None
        return data


class StockCountSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(source='lines.count', read_only=True)
    products = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), many=True, write_only=True, required=False,
        help_text='Optional: count only these products (a cycle count).',
    )

    class Meta:
        model = StockCount
        fields = ['id', 'store', 'store_name', 'status', 'note', 'created_by_name', 'created_at',
                  'submitted_by_name', 'submitted_at', 'approved_by_name', 'approved_at', 'line_count', 'products']
        read_only_fields = ['status', 'created_at', 'submitted_at', 'approved_at']

    def get_created_by_name(self, obj):
        return _name(obj.created_by)

    def get_submitted_by_name(self, obj):
        return _name(obj.submitted_by)

    def get_approved_by_name(self, obj):
        return _name(obj.approved_by)

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))


class StockCountDetailSerializer(StockCountSerializer):
    lines = StockCountLineSerializer(many=True, read_only=True)

    class Meta(StockCountSerializer.Meta):
        fields = StockCountSerializer.Meta.fields + ['lines']


class CountEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    counted_qty = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, allow_null=True)


class FoundStockSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    batch_no = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    expiry_date = serializers.DateField(required=False, allow_null=True, default=None)
    counted_qty = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
