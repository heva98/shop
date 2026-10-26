import uuid

from django.db import models


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

    @property
    def requires_reference(self):
        return self.implementation != self.Implementation.CASH

    def __str__(self):
        return self.name
