import uuid

from django.db import models
from django.db.models import Exists, OuterRef, Q


class PaymentMethod(models.Model):
    """Cash and mobile money are active out of the box (seeded by
    migration 0003). Mobile money and bank transfer are recorded manually
    for now: the customer pays on their phone or at the bank, and the
    cashier enters the transaction reference on the sale. An aggregator
    integration (Selcom, AzamPay, ...) later becomes a PaymentProcessor
    (see payments/interfaces.py) without changing POS code."""

    class Implementation(models.TextChoices):
        CASH = 'cash', 'Cash'
        MOBILE_MONEY = 'mobile_money', 'Mobile Money'
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=64)
    implementation = models.CharField(max_length=20, choices=Implementation.choices)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    @classmethod
    def active_for(cls, entity):
        """The methods `entity`'s tills offer: its own switch where it set
        one, else the platform default (is_active)."""
        own = EntityPaymentMethod.objects.filter(method=OuterRef('pk'), entity=entity)
        return cls.objects.filter(Exists(own.filter(is_active=True)) | (Q(is_active=True) & ~Exists(own)))

    def is_active_for(self, entity):
        own = EntityPaymentMethod.objects.filter(method=self, entity=entity).first()
        return own.is_active if own is not None else self.is_active

    @property
    def requires_reference(self):
        return self.implementation != self.Implementation.CASH

    def __str__(self):
        return self.name


class EntityPaymentMethod(models.Model):
    """One firm's own on/off switch for a PaymentMethod. PaymentMethod rows
    are shared by every firm on the server, so a firm's Settings toggle
    writes here instead; with no row the method's own is_active applies."""
    entity = models.ForeignKey('core.Entity', on_delete=models.CASCADE, related_name='payment_methods')
    method = models.ForeignKey(PaymentMethod, on_delete=models.CASCADE, related_name='entity_settings')
    is_active = models.BooleanField()

    class Meta:
        unique_together = [('entity', 'method')]

    def __str__(self):
        return f'{self.method} @ {self.entity} = {self.is_active}'
