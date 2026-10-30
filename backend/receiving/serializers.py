from rest_framework import serializers

from core.serializers import ClientGeneratedIdMixin, validate_accessible_store, validate_owned, validate_owned_entity

from .models import ReceivingInvoice, ReceivingInvoiceLine, Supplier, SupplierPayment


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ['id', 'entity', 'name', 'description', 'location', 'email', 'phone', 'payment_terms_days']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


class ReceivingInvoiceLineSerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    uom_name = serializers.CharField(source='uom.name', read_only=True)

    class Meta:
        model = ReceivingInvoiceLine
        fields = [
            'id', 'invoice', 'product', 'product_name', 'uom', 'uom_name',
            'order_qty', 'pack_price', 'batch_no', 'expiry_date', 'batch_qty',
        ]
        extra_kwargs = {'invoice': {'required': False}}

    def validate_invoice(self, invoice):
        """Only relevant when this serializer is used standalone (the
        ReceivingInvoiceLineViewSet — appending a line to a draft invoice
        someone resumes later); the nested-under-invoice create path never
        passes `invoice` in the payload, so this is skipped there."""
        validate_accessible_store(invoice.store, self.context.get('request'))
        return invoice

    def validate_product(self, product):
        return validate_owned(product, self.context.get('request'), 'Unknown product.')

    def validate_uom(self, uom):
        return validate_owned(uom, self.context.get('request'), 'Unknown unit of measure.')


class SupplierPaymentSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.SerializerMethodField()
    method_label = serializers.CharField(source='get_method_display', read_only=True)

    class Meta:
        model = SupplierPayment
        fields = ['id', 'amount', 'paid_on', 'method', 'method_label', 'reference', 'recorded_by_name', 'created_at']
        read_only_fields = ['id', 'recorded_by_name', 'created_at']

    def get_recorded_by_name(self, payment):
        return payment.recorded_by.get_full_name() or payment.recorded_by.username


class ReceivingInvoiceSerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    lines = ReceivingInvoiceLineSerializer(many=True, required=False)
    payments = SupplierPaymentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = ReceivingInvoice
        fields = [
            'id', 'store', 'supplier', 'supplier_name', 'invoice_number', 'received_date', 'due_date', 'status',
            'created_at', 'received_at', 'lines', 'total', 'amount_paid', 'balance', 'payments',
        ]
        read_only_fields = ['status', 'received_at']

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def validate(self, attrs):
        store = attrs.get('store', getattr(self.instance, 'store', None))
        supplier = attrs.get('supplier', getattr(self.instance, 'supplier', None))
        if store and supplier and supplier.entity_id != store.entity_id:
            raise serializers.ValidationError({'supplier': 'Supplier must belong to the invoice\'s entity.'})
        if self.instance is not None and self.instance.status == ReceivingInvoice.Status.RECEIVED:
            raise serializers.ValidationError('A received invoice can no longer be changed.')
        return attrs

    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        invoice = ReceivingInvoice.objects.create(**validated_data)
        for line_data in lines_data:
            ReceivingInvoiceLine.objects.create(invoice=invoice, **line_data)
        return invoice
