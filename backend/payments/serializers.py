from rest_framework import serializers

from .models import PaymentMethod


class PaymentMethodSerializer(serializers.ModelSerializer):
    """`is_active` reads and writes the caller's own firm's switch (see
    EntityPaymentMethod); for a superuser with no firm it is the platform
    default every firm without its own switch follows."""

    class Meta:
        model = PaymentMethod
        fields = ['id', 'name', 'implementation', 'is_active']
        read_only_fields = ['name', 'implementation']

    def to_representation(self, method):
        data = super().to_representation(method)
        entity = self.context.get('entity')
        if entity is not None:
            data['is_active'] = method.is_active_for(entity)
        return data
