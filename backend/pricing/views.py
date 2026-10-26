from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets

from audit.services import Action, record
from core.models import Role
from core.permissions import write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin, accessible_store_ids

from .models import Bundle, Price, Promotion
from .serializers import BundleSerializer, PriceSerializer, PromotionSerializer

_PRICING_ROLES = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)


class PriceViewSet(viewsets.ModelViewSet):
    """Scoped by core.Entity.price_mode (see Price docstring): entity-wide
    rows (store null) stay visible to everyone in the entity; per-store
    rows are further restricted to the stores the user holds a role at."""
    queryset = Price.objects.select_related('product', 'entity', 'store', 'uom').all()
    serializer_class = PriceSerializer
    filterset_fields = ['product', 'store', 'entity', 'uom']
    permission_classes = [write_roles(*_PRICING_ROLES)]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.entity_id is None:
            return qs.none()
        qs = qs.filter(entity_id=user.entity_id)
        store_ids = accessible_store_ids(user)
        if store_ids is not None:
            qs = qs.filter(Q(store__isnull=True) | Q(store_id__in=list(store_ids)))
        return qs

    @staticmethod
    def _label(price):
        unit = price.uom.name if price.uom_id else price.product.uom.name
        where = f' at {price.store.name}' if price.store_id else ''
        return f'{price.product.name} per {unit}{where}'

    def perform_create(self, serializer):
        price = serializer.save()
        record(Action.PRICE_SET, f'{self._label(price)}: set to {price.unit_price:,.0f}', request=self.request,
               store=price.store, entity=price.entity, data={'product': price.product.name, 'new': price.unit_price})

    def perform_update(self, serializer):
        old = serializer.instance.unit_price
        price = serializer.save()
        if price.unit_price != old:
            record(Action.PRICE_SET, f'{self._label(price)}: {old:,.0f} -> {price.unit_price:,.0f}',
                   request=self.request, store=price.store, entity=price.entity,
                   data={'product': price.product.name, 'old': old, 'new': price.unit_price})

    def perform_destroy(self, instance):
        label, store, entity, old = self._label(instance), instance.store, instance.entity, instance.unit_price
        instance.delete()
        record(Action.PRICE_REMOVED, f'{label}: price {old:,.0f} removed', request=self.request,
               store=store, entity=entity)


class BundleViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Bundle.objects.select_related('entity').prefetch_related('products').all()
    serializer_class = BundleSerializer
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_PRICING_ROLES)]


class PromotionViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Time-limited promotional prices (see pricing.Promotion). Everyone
    can read them; managers set them. ?running=true lists only those in
    force today."""
    queryset = Promotion.objects.select_related('product', 'uom', 'store', 'entity').all()
    serializer_class = PromotionSerializer
    filterset_fields = ['product', 'store', 'is_active']
    search_fields = ['name', 'product__name']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_PRICING_ROLES)]

    def get_queryset(self):
        qs = super().get_queryset()
        store_ids = accessible_store_ids(self.request.user)
        if store_ids is not None:
            qs = qs.filter(Q(store__isnull=True) | Q(store_id__in=list(store_ids)))
        if self.request.query_params.get('running') == 'true':
            today = timezone.localdate()
            qs = qs.filter(is_active=True, starts_on__lte=today, ends_on__gte=today)
        return qs

    @staticmethod
    def _label(promotion):
        where = f' at {promotion.store.name}' if promotion.store_id else ''
        return (f'{promotion.name}: {promotion.product.name} at {promotion.promo_price:,.0f}{where}, '
                f'{promotion.starts_on:%d/%m/%Y} to {promotion.ends_on:%d/%m/%Y}')

    def perform_create(self, serializer):
        promotion = serializer.save(entity=self.request.user.entity)
        record(Action.PROMOTION_CHANGED, f'Promotion added — {self._label(promotion)}', request=self.request,
               store=promotion.store, entity=promotion.entity)

    def perform_update(self, serializer):
        promotion = serializer.save()
        state = '' if promotion.is_active else ' (switched off)'
        record(Action.PROMOTION_CHANGED, f'Promotion changed — {self._label(promotion)}{state}', request=self.request,
               store=promotion.store, entity=promotion.entity)

    def perform_destroy(self, instance):
        label, store, entity = self._label(instance), instance.store, instance.entity
        instance.delete()
        record(Action.PROMOTION_CHANGED, f'Promotion removed — {label}', request=self.request, store=store, entity=entity)
