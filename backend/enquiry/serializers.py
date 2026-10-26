from decimal import Decimal

from rest_framework import serializers

from catalog.models import Product
from core.models import Store
from core.serializers import ClientGeneratedIdMixin, validate_accessible_store, validate_owned_store
from inventory.models import StockBatch
from payments.models import PaymentMethod

from .models import Enquiry, EnquiryLine, Transfer, TransferLine


class EnquiryLineSerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    unit = serializers.CharField(source='product.uom.name', read_only=True, default='')

    class Meta:
        model = EnquiryLine
        fields = ['id', 'enquiry', 'product', 'product_name', 'unit', 'qty_requested']
        extra_kwargs = {'enquiry': {'required': False}}

    def validate_qty_requested(self, qty):
        if qty <= 0:
            raise serializers.ValidationError('Must be more than zero.')
        return qty


class EnquirySerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    """mode and target_store are decided by the firm's set-up, not by the
    client: a branch of a hub firm asks the main store; everyone else
    posts to the shared board."""
    lines = EnquiryLineSerializer(many=True, required=False)
    requesting_store_name = serializers.CharField(source='requesting_store.name', read_only=True)
    target_store_name = serializers.CharField(source='target_store.name', read_only=True, default=None)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = [
            'id', 'requesting_store', 'requesting_store_name', 'mode',
            'target_store', 'target_store_name', 'status', 'note', 'created_by_name', 'created_at', 'lines',
        ]
        read_only_fields = ['status', 'mode', 'target_store']

    def get_created_by_name(self, enquiry):
        user = enquiry.created_by
        return (user.get_full_name() or user.username) if user else ''

    def validate_requesting_store(self, store):
        """The filer's own store — must actually be one they operate,
        not merely in the same firm."""
        return validate_accessible_store(store, self.context.get('request'))

    def validate_lines(self, lines):
        request = self.context.get('request')
        for line in lines:
            product = line['product']
            if request and not request.user.is_superuser and product.entity_id != request.user.entity_id:
                raise serializers.ValidationError("Product is not in this shop's catalog.")
        return lines

    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        if not lines_data:
            raise serializers.ValidationError({'lines': 'Add at least one product.'})
        store = validated_data['requesting_store']
        main_store_id = store.entity.main_store_id
        if main_store_id and main_store_id != store.id:
            validated_data.update(mode=Enquiry.Mode.HUB, target_store_id=main_store_id)
        else:
            validated_data.update(mode=Enquiry.Mode.BROADCAST, target_store=None)
        enquiry = Enquiry.objects.create(**validated_data)
        for line_data in lines_data:
            EnquiryLine.objects.create(enquiry=enquiry, **line_data)
        return enquiry


class TransferLineSerializer(serializers.ModelSerializer):
    product = serializers.UUIDField(source='batch.product_id', read_only=True)
    product_name = serializers.CharField(source='batch.product.name', read_only=True)
    unit = serializers.CharField(source='batch.product.uom.name', read_only=True, default='')
    batch_no = serializers.CharField(source='batch.batch_no', read_only=True)
    expiry_date = serializers.DateField(source='batch.expiry_date', read_only=True)

    class Meta:
        model = TransferLine
        fields = ['id', 'batch', 'product', 'product_name', 'unit', 'batch_no', 'expiry_date',
                  'qty', 'received_qty', 'unit_cost']


def _name(user):
    return (user.get_full_name() or user.username) if user else ''


class TransferSerializer(serializers.ModelSerializer):
    """Read shape. Transfers are created through TransferCreateSerializer
    (or an enquiry's fulfil action) and change only through the model's
    own actions — confirm receipt, resolve, cancel, record payment."""
    lines = TransferLineSerializer(many=True, read_only=True)
    from_store_name = serializers.CharField(source='from_store.name', read_only=True)
    to_store_name = serializers.CharField(source='to_store.name', read_only=True)
    dispatched_by_name = serializers.SerializerMethodField()
    received_by_name = serializers.SerializerMethodField()
    payment_method_name = serializers.CharField(source='payment_method.name', read_only=True, default='')
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    resolution_label = serializers.CharField(source='get_resolution_display', read_only=True)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Transfer
        fields = [
            'id', 'number', 'enquiry', 'from_store', 'from_store_name', 'to_store', 'to_store_name', 'mode',
            'status', 'status_label', 'note', 'dispatched_by_name', 'received_by_name', 'discrepancy_note',
            'resolution', 'resolution_label', 'amount', 'balance', 'payment_method', 'payment_method_name',
            'payment_reference', 'paid_at', 'dispatched_at', 'received_at', 'lines',
        ]
        read_only_fields = fields

    def get_dispatched_by_name(self, transfer):
        return _name(transfer.dispatched_by)

    def get_received_by_name(self, transfer):
        return _name(transfer.received_by)


class TransferItemSerializer(serializers.Serializer):
    """One line to send: a product (batches picked earliest-expiry first)
    or a specific batch, and a quantity in the product's own unit."""
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), required=False)
    batch = serializers.PrimaryKeyRelatedField(queryset=StockBatch.objects.all(), required=False)
    qty = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))

    def validate(self, attrs):
        if not attrs.get('product') and not attrs.get('batch'):
            raise serializers.ValidationError('Choose a product.')
        return attrs


class TransferCreateSerializer(serializers.Serializer):
    from_store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    to_store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    lines = TransferItemSerializer(many=True)

    def validate_from_store(self, store):
        """The dispatching store — the user must actually operate it,
        since sending deducts its stock immediately."""
        return validate_accessible_store(store, self.context.get('request'))

    def validate_to_store(self, store):
        """The receiving store — same-entity is enough; the dispatcher
        doesn't need a role there."""
        return validate_owned_store(store, self.context.get('request'))

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError('Add at least one product to send.')
        return lines


class ConfirmReceiptSerializer(serializers.Serializer):
    received_qty_by_line = serializers.DictField(
        child=serializers.DecimalField(max_digits=12, decimal_places=2), required=False, default=dict)
    note = serializers.CharField(required=False, allow_blank=True, default='')


class ResolveSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=Transfer.Resolution.choices)
    note = serializers.CharField(required=False, allow_blank=True, default='')


class CancelTransferSerializer(serializers.Serializer):
    reason = serializers.CharField()


class TransferPaymentSerializer(serializers.Serializer):
    payment_method = serializers.PrimaryKeyRelatedField(queryset=PaymentMethod.objects.all())
    reference = serializers.CharField(required=False, allow_blank=True, default='')
