import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from core.models import Entity


class Category(models.Model):
    """Entity-wide, like Product — each firm keeps its own list of
    categories (Beverages, Cereals & flour, Toiletries...) rather than
    sharing one across every tenant on the platform."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class UnitOfMeasure(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='units_of_measure')
    name = models.CharField(max_length=64)
    description = models.CharField(max_length=255, blank=True)
    unit_value = models.DecimalField(max_digits=10, decimal_places=2, help_text='e.g. Crate = 24 bottles -> 24')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UnitConversionError(ValueError):
    """A quantity in one unit isn't a whole number of hundredths in
    another, e.g. 1 Pack of 3 expressed in Packs of 10. Mapped to HTTP 400
    by config.exceptions.custom_exception_handler."""


def convert_qty(qty, from_uom, to_uom):
    """`qty` of `from_uom` expressed in `to_uom`. Every unit's unit_value
    counts the same smallest piece (bottle, packet, piece...), so Carton of
    48 -> Dozen is 48/12 = 4 dozen per carton.

    Stock is always held in the product's own unit (Product.uom), so
    receiving converts supplier packs into it and the till converts the
    unit it sells in into it."""
    if from_uom is None or to_uom is None or from_uom.pk == to_uom.pk:
        return Decimal(qty)
    converted = Decimal(qty) * Decimal(from_uom.unit_value) / Decimal(to_uom.unit_value)
    rounded = converted.quantize(Decimal('0.01'))
    if abs(converted - rounded) > Decimal('0.000001'):
        raise UnitConversionError(
            f'{qty} {from_uom.name} is not a whole number of {to_uom.name} ({converted:.4f}).',
        )
    return rounded


class Product(models.Model):
    """Entity-wide master catalog — shared by every store *within one
    firm*, but never across firms. Per-store restriction/config lives in
    inventory.StoreProduct — this table is never store-scoped."""

    class VatClass(models.TextChoices):
        EXEMPT = 'exempt', 'Exempt'
        ZERO_RATED = 'zero_rated', 'Zero-rated'
        STANDARD = 'standard', 'Standard'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='products')
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.SET_NULL, related_name='products',
    )
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=128, blank=True, help_text='e.g. Azam, Kilimanjaro, Colgate')
    size = models.CharField(max_length=64, blank=True, help_text='e.g. 500 ml, 2 kg, 100 g tube')
    vat_class = models.CharField(max_length=10, choices=VatClass.choices, default=VatClass.STANDARD)
    uom = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, related_name='products',
        help_text='The smallest unit this product is stocked, counted and sold in. Stock quantities '
                  'are always in this unit; larger packs (cartons, crates) convert into it.',
    )
    barcode = models.CharField(max_length=64, blank=True, db_index=True)
    tracks_expiry = models.BooleanField(
        default=False,
        help_text='Perishable goods (food, drinks, cosmetics). Receiving then asks for an expiry date, '
                  'stock sells earliest-expiry first and expired stock cannot be sold.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'barcode'], condition=~models.Q(barcode=''), name='unique_barcode_per_entity',
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.category_id and self.category.entity_id != self.entity_id:
            raise ValidationError({'category': 'Category must belong to the same entity as the product.'})
        if self.uom_id and self.uom.entity_id != self.entity_id:
            raise ValidationError({'uom': 'Unit of measure must belong to the same entity as the product.'})
