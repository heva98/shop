import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from catalog.models import Product, UnitOfMeasure
from core.models import Entity, Store


class Price(models.Model):
    """Scoped by core.Entity.price_mode, chosen once at onboarding:
    store null = one price list shared by every store in the entity;
    store set = each store prices this product independently. Callers
    pricing a sale should use get_price() rather than querying directly,
    since which row applies depends on the entity's mode.

    uom null = the price of one Product.uom (the unit stock is held in).
    uom set = the price when selling in that other unit, e.g. a Strip of 10
    when the product is stocked in tablets — often cheaper per tablet, so
    it is set explicitly rather than multiplied out."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='prices')
    store = models.ForeignKey(
        Store, null=True, blank=True, on_delete=models.CASCADE, related_name='prices',
        help_text='Null when entity.price_mode = "entity"; required when "store".',
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='prices')
    uom = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text="Null = per the product's own unit. Set = price when selling in this other unit.",
    )
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__name']
        constraints = [
            models.UniqueConstraint(
                fields=['entity', 'product'], condition=models.Q(store__isnull=True, uom__isnull=True),
                name='unique_entity_wide_price',
            ),
            models.UniqueConstraint(
                fields=['entity', 'store', 'product'], condition=models.Q(store__isnull=False, uom__isnull=True),
                name='unique_store_price',
            ),
            models.UniqueConstraint(
                fields=['entity', 'product', 'uom'], condition=models.Q(store__isnull=True, uom__isnull=False),
                name='unique_entity_wide_unit_price',
            ),
            models.UniqueConstraint(
                fields=['entity', 'store', 'product', 'uom'], condition=models.Q(store__isnull=False, uom__isnull=False),
                name='unique_store_unit_price',
            ),
        ]

    def __str__(self):
        return f'{self.product} @ {self.store or self.entity}: {self.unit_price}'

    def save(self, *args, **kwargs):
        # A price "per Tablet" for a product stocked in tablets is just its
        # base price; keep one row for it, not two.
        if self.uom_id is not None and self.uom_id == self.product.uom_id:
            self.uom = None
        super().save(*args, **kwargs)

    def clean(self):
        if self.store_id and self.store.entity_id != self.entity_id:
            raise ValidationError({'store': 'Store must belong to the priced entity.'})
        if self.entity.price_mode == Entity.PriceMode.STORE and self.store_id is None:
            raise ValidationError({'store': 'This entity prices per store — store is required.'})
        if self.entity.price_mode == Entity.PriceMode.ENTITY and self.store_id is not None:
            raise ValidationError({'store': 'This entity uses one shared price list — leave store empty.'})

    @classmethod
    def get_price(cls, *, entity, product, store=None, uom=None):
        """The sanctioned lookup — respects entity.price_mode so callers
        never have to know which shape of row applies. `uom` None (or the
        product's own unit) = the base price."""
        uom_filter = {'uom__isnull': True} if uom is None or uom.pk == product.uom_id else {'uom': uom}
        if entity.price_mode == Entity.PriceMode.STORE:
            return cls.objects.get(entity=entity, store=store, product=product, **uom_filter)
        return cls.objects.get(entity=entity, store__isnull=True, product=product, **uom_filter)


class Bundle(models.Model):
    """Optional module — some deployments may not need combined pricing.
    Entity-wide only: unlike Price, not affected by entity.price_mode."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='bundles')
    name = models.CharField(max_length=255)
    products = models.ManyToManyField(Product, related_name='bundles')
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Promotion(models.Model):
    """A time-limited selling price, e.g. "Soda 500ml at 800 this weekend".
    While it runs, the till charges promo_price instead of the regular
    Price for that product and unit; nothing else about selling changes.

    store null = at every store; set = at that store only (and it wins
    over an entity-wide promotion for the same product). uom works as on
    Price. Ends at the end of ends_on (inclusive)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='promotions')
    store = models.ForeignKey(
        Store, null=True, blank=True, on_delete=models.CASCADE, related_name='promotions',
        help_text='Null = runs at every store.',
    )
    name = models.CharField(max_length=128, help_text='e.g. "Weekend soda offer"')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='promotions')
    uom = models.ForeignKey(
        UnitOfMeasure, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
        help_text="Null = per the product's own unit.",
    )
    promo_price = models.DecimalField(max_digits=12, decimal_places=2)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=True, help_text='Switch off to end a promotion early.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-starts_on', 'product__name']
        indexes = [models.Index(fields=['entity', 'product', 'starts_on', 'ends_on'])]

    def __str__(self):
        return f'{self.name}: {self.product} at {self.promo_price}'

    def save(self, *args, **kwargs):
        if self.uom_id is not None and self.uom_id == self.product.uom_id:
            self.uom = None
        super().save(*args, **kwargs)

    @property
    def is_running(self):
        today = timezone.localdate()
        return self.is_active and self.starts_on <= today <= self.ends_on

    @classmethod
    def running(cls, *, store, on=None):
        """Promotions in force at `store` on `on` (default today), the
        store's own first."""
        on = on or timezone.localdate()
        return (cls.objects.filter(entity_id=store.entity_id, is_active=True, starts_on__lte=on, ends_on__gte=on)
                .filter(models.Q(store__isnull=True) | models.Q(store=store))
                .order_by(models.F('store').asc(nulls_last=True), '-starts_on'))


def effective_price(*, store, product, uom=None, on=None):
    """(unit_price, promotion) the till charges at `store` today for one
    `uom` of `product`: a running promotion's price when there is one,
    else the regular Price. (None, None) when neither is set."""
    sell_uom = uom if uom is not None and uom.pk != product.uom_id else None
    promotion = Promotion.running(store=store, on=on).filter(product=product, uom=sell_uom).first()
    if promotion is not None:
        return promotion.promo_price, promotion
    try:
        return Price.get_price(entity=store.entity, product=product, store=store, uom=sell_uom).unit_price, None
    except Price.DoesNotExist:
        return None, None
