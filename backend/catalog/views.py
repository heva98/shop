from rest_framework import viewsets

from audit.services import Action, record
from core.models import Role
from core.permissions import write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin

from .models import Category, Product, UnitOfMeasure
from .serializers import CategorySerializer, ProductSerializer, UnitOfMeasureSerializer

_CATALOG_WRITE_ROLES = (Role.ENTITY_ADMIN,)


class CategoryViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    search_fields = ['name', 'short_name']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_CATALOG_WRITE_ROLES)]


class UnitOfMeasureViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = UnitOfMeasure.objects.all()
    serializer_class = UnitOfMeasureSerializer
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_CATALOG_WRITE_ROLES)]


class ProductViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Entity-wide master catalog — shared by every store within one firm,
    scoped so it's never visible across firms (see catalog.Product's
    docstring). architecture.txt gates catalog edits online-only (sync
    §4) — enforce that at the client/sync layer, not here, since this
    endpoint is itself the online path."""
    queryset = Product.objects.select_related('category', 'uom').all()
    serializer_class = ProductSerializer
    filterset_fields = ['category', 'vat_class', 'tracks_expiry', 'barcode']
    search_fields = ['name', 'short_name', 'brand', 'size', 'barcode', 'category__name']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_CATALOG_WRITE_ROLES)]

    # A changed barcode or unit changes what the till rings up, so product
    # edits are audited.
    _TRACKED = ('name', 'size', 'uom_id', 'vat_class', 'barcode', 'tracks_expiry', 'category_id')

    def perform_create(self, serializer):
        product = serializer.save()
        record(Action.PRODUCT_CREATED, f'Product {product.name} added', request=self.request, entity=product.entity)

    def perform_update(self, serializer):
        before = {f: getattr(serializer.instance, f) for f in self._TRACKED}
        product = serializer.save()
        changed = {f: [before[f], getattr(product, f)] for f in self._TRACKED if getattr(product, f) != before[f]}
        if changed:
            record(Action.PRODUCT_UPDATED, f'Product {product.name} changed: {", ".join(changed)}',
                   request=self.request, entity=product.entity, data=changed)
