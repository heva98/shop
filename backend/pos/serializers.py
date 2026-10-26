from decimal import Decimal

from rest_framework import serializers

from catalog.models import Product, UnitOfMeasure
from core.models import Store
from core.serializers import ClientGeneratedIdMixin, validate_accessible_store
from credit.models import Customer
from payments.models import PaymentMethod

from .models import Sale, SaleLine, Shift


class SaleLineSerializer(serializers.ModelSerializer):
    product = serializers.UUIDField(source='batch.product_id', read_only=True)
    product_name = serializers.CharField(source='batch.product.name', read_only=True)
    batch_no = serializers.CharField(source='batch.batch_no', read_only=True)
    expiry_date = serializers.DateField(source='batch.expiry_date', read_only=True)
    unit_name = serializers.CharField(read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = SaleLine
        fields = ['id', 'batch', 'batch_no', 'expiry_date', 'product', 'product_name',
                  'qty', 'sell_uom', 'sell_qty', 'unit_name', 'unit_price', 'discount', 'vat_class', 'amount',
                  'line_total']
        read_only_fields = fields


class SaleItemSerializer(serializers.Serializer):
    """A cart line as the till sends it: product, quantity, optionally the
    unit it's sold in (default: the product's own unit) and an amount off
    the whole item. The price and the batch are always decided
    server-side."""
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    qty = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    uom = serializers.PrimaryKeyRelatedField(queryset=UnitOfMeasure.objects.all(), required=False, allow_null=True)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False,
                                        default=Decimal('0'))


class SaleSerializer(ClientGeneratedIdMixin, serializers.ModelSerializer):
    lines = SaleLineSerializer(many=True, read_only=True)
    items = SaleItemSerializer(many=True, write_only=True, required=False)
    total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    vat_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    discount_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    change_due = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    payment_method_name = serializers.CharField(source='payment_method.name', read_only=True, default='')
    paid_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True, default='')
    cashier_name = serializers.SerializerMethodField()
    voided_by_name = serializers.SerializerMethodField()
    void_approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            'id', 'store', 'status', 'number', 'cashier', 'cashier_name', 'shift',
            'payment_method', 'payment_method_name', 'amount_tendered', 'change_due', 'payment_reference',
            'customer', 'customer_name', 'customer_phone', 'credit_amount', 'paid_amount',
            'efd_receipt_no', 'created_at', 'completed_at',
            'voided_at', 'voided_by_name', 'void_approved_by_name', 'void_reason',
            'lines', 'items', 'total', 'vat_total', 'discount_total',
        ]
        read_only_fields = [
            'status', 'number', 'cashier', 'shift', 'payment_method', 'amount_tendered', 'payment_reference',
            'customer', 'customer_name', 'credit_amount', 'efd_receipt_no', 'completed_at',
            'voided_at', 'void_reason',
        ]

    @staticmethod
    def _name(user):
        return (user.get_full_name() or user.username) if user else ''

    def get_cashier_name(self, sale):
        return self._name(sale.cashier)

    def get_voided_by_name(self, sale):
        return self._name(sale.voided_by)

    def get_void_approved_by_name(self, sale):
        return self._name(sale.void_approved_by)

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def create(self, validated_data):
        items = validated_data.pop('items', [])
        sale = Sale.objects.create(**validated_data)
        for item in items:
            sale.add_product(product=item['product'], qty=item['qty'], uom=item.get('uom'),
                             discount=item.get('discount') or Decimal('0'))
        return sale


class AddLineSerializer(SaleItemSerializer):
    """Input for Sale.add_product — by product, not batch; the batch is
    resolved server-side by FEFO and the price from pricing (a running
    Promotion, else the regular Price)."""


class CompleteSaleSerializer(serializers.Serializer):
    """`discount` comes off the whole sale, on top of any line discounts.
    Beyond the cashier's limit a manager approves it by entering their own
    username and password at the till (approver_*), as for a void.
    `credit_amount` of the total goes on `customer`'s account."""
    payment_method = serializers.PrimaryKeyRelatedField(queryset=PaymentMethod.objects.all())
    amount_tendered = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    payment_reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all(), required=False, allow_null=True)
    credit_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'),
                                             required=False, default=Decimal('0'))
    customer_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'),
                                       required=False, default=Decimal('0'))
    approver_username = serializers.CharField(required=False, allow_blank=True, default='')
    approver_password = serializers.CharField(required=False, allow_blank=True, default='', trim_whitespace=False)



class OfflineSaleItemSerializer(SaleItemSerializer):
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))


class OfflineSaleSerializer(CompleteSaleSerializer):
    """A whole sale the till rang up from its own copy of the catalog (see
    Sale.record_offline). `id` is the till's own, so sending the same sale
    twice records it once."""
    id = serializers.UUIDField()
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    shift = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.all(), required=False, allow_null=True)
    completed_at = serializers.DateTimeField(required=False, allow_null=True)
    strict = serializers.BooleanField(required=False, default=False)
    items = OfflineSaleItemSerializer(many=True, allow_empty=False)
    efd_receipt_no = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))


class RecordFiscalSerializer(serializers.Serializer):
    receipt_number = serializers.CharField(max_length=64)


class VoidSaleSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    approver_username = serializers.CharField(required=False, allow_blank=True, default='')
    approver_password = serializers.CharField(required=False, allow_blank=True, default='', trim_whitespace=False)


class ShiftSerializer(serializers.ModelSerializer):
    cashier_name = serializers.SerializerMethodField()
    store_name = serializers.CharField(source='store.name', read_only=True)
    is_open = serializers.BooleanField(read_only=True)

    class Meta:
        model = Shift
        fields = [
            'id', 'store', 'store_name', 'cashier', 'cashier_name', 'opened_at', 'opening_float',
            'closed_at', 'counted_cash', 'expected_cash', 'closing_note', 'is_open',
        ]
        read_only_fields = ['cashier', 'opened_at', 'closed_at', 'counted_cash', 'expected_cash', 'closing_note']

    def get_cashier_name(self, shift):
        return shift.cashier.get_full_name() or shift.cashier.username

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def validate_opening_float(self, value):
        if value < 0:
            raise serializers.ValidationError('Opening float cannot be negative.')
        return value


class CloseShiftSerializer(serializers.Serializer):
    counted_cash = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    note = serializers.CharField(required=False, allow_blank=True, default='')
