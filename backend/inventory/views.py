from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import Action, Summary, record
from core.models import Role
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin
from core.serializers import validate_accessible_store

from .models import StockAdjustment, StockBatch, StockCount, StockLedger, StoreProduct
from .serializers import (
    CountEntrySerializer, FoundStockSerializer, StockAdjustmentSerializer, StockBatchSerializer,
    StockCountDetailSerializer, StockCountSerializer, StockLedgerSerializer, StoreProductSerializer,
)
from .services import adjustments, counts

_STOCK_ROLES = (Role.CASHIER, Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)
_COUNT_ROLES = (Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)
_MANAGER_ROLES = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)


class StoreProductViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = StoreProduct.objects.select_related('store', 'product').all()
    serializer_class = StoreProductSerializer
    filterset_fields = ['store', 'product', 'enabled']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_STOCK_ROLES)]


class StockBatchViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Quantities never change here (qty_on_hand is read-only — only the
    ledger moves stock), and a batch is never deleted: its ledger history
    has to stay."""
    queryset = StockBatch.objects.select_related('store', 'product__uom').all()
    serializer_class = StockBatchSerializer
    filterset_fields = ['store', 'product']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_COUNT_ROLES)]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']


class StockLedgerViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """Append-only: writes happen only via inventory.stock.record_movement() from the
    module that owns the movement (pos.services.checkout, Transfer.dispatch /
    confirm_receipt, ReceivingInvoice.mark_received, StockAdjustment,
    StockCount.approve) — never directly here.
    """
    queryset = StockLedger.objects.select_related('store', 'batch__product').all()
    serializer_class = StockLedgerSerializer
    filterset_fields = ['store', 'batch', 'ledger_type', 'ref_type']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)


class StockAdjustmentViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """POST {batch, qty_delta, reason, note} writes stock off (negative
    qty_delta) with a reason. POST .../write_off_expired/ {store} writes off
    every expired batch still holding stock in one go. Managers only;
    adjustments are never edited or deleted."""
    queryset = StockAdjustment.objects.select_related('store', 'batch__product', 'created_by').all()
    serializer_class = StockAdjustmentSerializer
    filterset_fields = ['store', 'reason', 'batch']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_MANAGER_ROLES)]
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if not is_store_manager(request.user, data['batch'].store):
            raise PermissionDenied(gettext('Only a manager of this store can adjust its stock.'))
        adjustment = adjustments.apply(
            batch=data['batch'], qty_delta=data['qty_delta'], reason=data['reason'],
            note=data.get('note', ''), user=request.user,
        )
        batch = adjustment.batch
        record(Action.STOCK_WRITTEN_OFF,
               Summary('{get_reason_display}: {qty_delta:+} {name} (batch {batch_no})', get_reason_display=adjustment.get_reason_display(), qty_delta=adjustment.qty_delta, name=batch.product.name, batch_no=batch.batch_no),
               request=request, store=batch.store,
               data={'qty': adjustment.qty_delta, 'reason': adjustment.reason, 'note': adjustment.note,
                     'value_at_cost': adjustment.qty_delta * batch.unit_cost})
        return Response(self.get_serializer(adjustment).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def write_off_expired(self, request):
        from core.models import Store
        store = Store.objects.filter(pk=request.data.get('store')).first()
        if store is None:
            raise ValidationError({'store': gettext('Choose a store.')})
        validate_accessible_store(store, request)
        if not is_store_manager(request.user, store):
            raise PermissionDenied(gettext('Only a manager of this store can write off stock.'))
        expired = StockBatch.objects.filter(store=store, qty_on_hand__gt=0, expiry_date__lt=timezone.localdate())
        with transaction.atomic():
            created = [
                adjustments.apply(
                    batch=batch, qty_delta=-batch.qty_on_hand, reason=StockAdjustment.Reason.EXPIRED,
                    note=f'Expired {batch.expiry_date:%d/%m/%Y}', user=request.user,
                )
                for batch in expired.select_related('product', 'store')
            ]
        if created:
            record(Action.STOCK_WRITTEN_OFF, Summary('All expired stock written off: {len} batch(es)', len=len(created)),
                   request=request, store=store,
                   data={'batches': [f'{a.batch.product.name} {a.batch.batch_no} ({a.qty_delta})' for a in created]})
        return Response(self.get_serializer(created, many=True).data, status=status.HTTP_201_CREATED)


class StockCountViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Stock take. POST {store, products?} starts a count with a line per
    batch on hand. While counting: .../save/ [{id, counted_qty}] and
    .../found/ {product, batch_no, expiry_date, counted_qty} for stock the
    system didn't know about; .../submit/ locks it. A manager then sees
    the differences and .../approve/s (or .../reopen/s); .../cancel/
    abandons it."""
    queryset = StockCount.objects.select_related('store', 'created_by', 'submitted_by', 'approved_by').all()
    filterset_fields = ['store', 'status']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_COUNT_ROLES)]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_serializer_class(self):
        return StockCountDetailSerializer if self.action != 'list' else StockCountSerializer

    def get_object(self):
        count = super().get_object()
        # Prefetch here, not on the list queryset: only detail views need lines.
        count = StockCount.objects.prefetch_related('lines__product__uom', 'lines__batch').get(pk=count.pk)
        return count

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        store = data['store']
        counts.check_none_in_progress(store)
        count = counts.start(store=store, user=request.user, products=data.get('products'), note=data.get('note', ''))
        return Response(StockCountDetailSerializer(StockCount.objects.get(pk=count.pk)).data, status=status.HTTP_201_CREATED)

    def _detail(self, count):
        count = StockCount.objects.prefetch_related('lines__product__uom', 'lines__batch').get(pk=count.pk)
        return Response(StockCountDetailSerializer(count).data)

    @action(detail=True, methods=['post'])
    def save(self, request, pk=None):
        count = self.get_object()
        counts.require_counting(count)
        entries = CountEntrySerializer(data=request.data, many=True)
        entries.is_valid(raise_exception=True)
        lines = {str(line.id): line for line in count.lines.all()}
        changed = []
        for entry in entries.validated_data:
            line = lines.get(str(entry['id']))
            if line is None:
                raise ValidationError(gettext('Line {id} is not part of this count.').format(id=entry["id"]))
            line.counted_qty = entry['counted_qty']
            changed.append(line)
        counts.record_counted(count, changed)
        return self._detail(count)

    @action(detail=True, methods=['post'])
    def found(self, request, pk=None):
        count = self.get_object()
        counts.require_counting(count)
        serializer = FoundStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['product'].entity_id != count.store.entity_id:
            raise ValidationError({'product': gettext("Product is not in this shop's catalog.")})
        counts.add_found_stock(count, product=data['product'], batch_no=data['batch_no'],
                               expiry_date=data['expiry_date'], counted_qty=data['counted_qty'])
        return self._detail(count)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        count = self.get_object()
        counts.submit(count, user=request.user)
        return self._detail(count)

    def _require_manager(self, count):
        if not is_store_manager(self.request.user, count.store):
            raise PermissionDenied(gettext('Only a manager of this store can do this.'))

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        count = self.get_object()
        self._require_manager(count)
        counts.approve(count, user=request.user)
        corrections = [line for line in count.lines.select_related('product', 'batch') if line.adjustment_qty]
        value = sum((line.adjustment_qty * (line.batch.unit_cost if line.batch else 0) for line in corrections), 0)
        record(Action.STOCK_COUNT_APPROVED,
               Summary('Stock count approved: {len} correction(s), value at cost {value:,.0f}', len=len(corrections), value=value),
               request=request, store=count.store, data={'count': str(count.id), 'value_at_cost': value})
        return self._detail(count)

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        count = self.get_object()
        self._require_manager(count)
        counts.reopen(count)
        return self._detail(count)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        count = self.get_object()
        if count.created_by_id != request.user.id:
            self._require_manager(count)
        counts.cancel(count)
        return self._detail(count)
