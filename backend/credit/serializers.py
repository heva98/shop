from decimal import Decimal

from rest_framework import serializers

from core.models import Store
from core.serializers import validate_accessible_store
from payments.models import PaymentMethod

from .models import Customer, CustomerPayment


def _name(user):
    return (user.get_full_name() or user.username) if user else ''


class CustomerSerializer(serializers.ModelSerializer):
    owing = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=Decimal('0'))
    credit_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=Decimal('0'))
    paid_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, default=Decimal('0'))

    class Meta:
        model = Customer
        fields = ['id', 'name', 'phone', 'address', 'note', 'credit_limit', 'is_active',
                  'owing', 'credit_total', 'paid_total', 'created_at']
        # Phone uniqueness is checked in validate_phone() with a message
        # that names the clashing customer.
        validators = []

    def validate_name(self, name):
        name = name.strip()
        if not name:
            raise serializers.ValidationError('Enter the customer\'s name.')
        return name

    def validate_phone(self, phone):
        phone = phone.strip().replace(' ', '')
        if phone:
            clash = Customer.objects.filter(entity=self.context['request'].user.entity, phone=phone)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(f'{clash.first().name} already has this phone number.')
        return phone

    def validate_credit_limit(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError('The credit limit cannot be negative.')
        return value


class CustomerPaymentSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    payment_method_name = serializers.CharField(source='payment_method.name', read_only=True)
    received_by_name = serializers.SerializerMethodField()
    voided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomerPayment
        fields = ['id', 'customer', 'customer_name', 'store', 'store_name', 'shift', 'amount', 'payment_method',
                  'payment_method_name', 'reference', 'note', 'received_by_name', 'created_at',
                  'voided_at', 'voided_by_name', 'void_reason']
        read_only_fields = fields

    def get_received_by_name(self, payment):
        return _name(payment.received_by)

    def get_voided_by_name(self, payment):
        return _name(payment.voided_by)


class ReceivePaymentSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    payment_method = serializers.PrimaryKeyRelatedField(queryset=PaymentMethod.objects.all())
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def validate_customer(self, customer):
        request = self.context.get('request')
        if request and not request.user.is_superuser and customer.entity_id != request.user.entity_id:
            raise serializers.ValidationError('Not one of your customers.')
        return customer


class VoidPaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
