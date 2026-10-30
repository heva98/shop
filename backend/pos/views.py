from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import Action, record
from catalog.models import Product, UnitOfMeasure
from catalog.serializers import UnitOfMeasureSerializer
from core import features
from core.models import Entity, Role, Store
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin, accessible_store_ids
from credit.models import Customer, with_balances
from inventory.models import StockBatch, sellable_batches
from payments.models import PaymentMethod
from payments.serializers import PaymentMethodSerializer
from pricing.models import Price, Promotion

from .models import Sale, SaleError, Shift
from .serializers import (
    AddLineSerializer, CloseShiftSerializer, CompleteSaleSerializer, OfflineSaleSerializer, RecordFiscalSerializer,
    SaleSerializer, ShiftSerializer, VoidSaleSerializer,
)

_POS_ROLES = (Role.CASHIER, Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)


def _manager_override(request, username, password, store):
    """The manager who typed their own username and password at the till
    to approve something (a void, a large discount), or None when nobody
    did. Wrong details are refused rather than ignored."""
    if not username or not password:
        return None
    approver = authenticate(request, username=username, password=password)
    if approver is None or not is_store_manager(approver, store):
        raise PermissionDenied('Approval failed: wrong username/password, or that user is not a manager at this store.')
    return approver


def _payment(data, request, store):
    """The keyword arguments Sale.complete takes, from a validated
    CompleteSaleSerializer / OfflineSaleSerializer payload."""
    data = dict(data)
    username, password = data.pop('approver_username', ''), data.pop('approver_password', '')
    data['discount_approver'] = _manager_override(request, username, password, store)
    return data


def _audit_discount(request, sale):
    """A discount over the cashier's limit is recorded with whoever
    allowed it — a manager at the till, or nobody (an offline sale)."""
    discount = sale.discount_total
    if not discount:
        return
    gross = sale.total + discount
    limit = sale.store.entity.cashier_discount_limit
    if discount * 100 <= gross * limit:
        return
    by = sale.discount_approved_by
    who = f'approved by {by.username}' if by else (
        'given by a manager' if is_store_manager(sale.cashier, sale.store) else 'made offline, not approved')
    record(Action.DISCOUNT_GIVEN, f'Sale #{sale.number}: discount TZS {discount:,.0f} of {gross:,.0f} ({who})',
           request=request, store=sale.store,
           data={'sale': str(sale.id), 'discount': discount, 'gross': gross,
                 'approved_by': by.username if by else ''})


class SaleViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """POST /sales/ with {store, items: [{product, qty}]} opens a sale and
    prices/allocates each item server-side (pricing.Price + FEFO). Then
    POST .../complete/ takes payment, deducts stock and locks it.

    There is deliberately no PUT/PATCH/DELETE: a completed sale is a
    financial record. Mistakes are corrected with .../void/ (manager
    approval required), and an abandoned cart with .../cancel/."""

    queryset = (Sale.objects.select_related('store__entity', 'payment_method', 'cashier', 'voided_by',
                                           'void_approved_by', 'discount_approved_by', 'customer')
                .prefetch_related('lines__batch__product__uom', 'lines__sell_uom').all())
    serializer_class = SaleSerializer
    filterset_fields = ['store', 'payment_method', 'status', 'shift', 'cashier', 'customer']
    search_fields = ['efd_receipt_no', 'payment_reference', 'customer_name']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_POS_ROLES)]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        qs = super().get_queryset()
        number = self.request.query_params.get('number')
        if number and number.isdigit():
            qs = qs.filter(number=int(number))
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        features.require('pos_sale', store=serializer.validated_data['store'])
        serializer.save(cashier=self.request.user)

    def _respond(self, sale, fiscal_result=None):
        sale = self.get_queryset().get(pk=sale.pk)
        data = self.get_serializer(sale).data
        if fiscal_result is not None:
            data['fiscal_result'] = {
                'success': fiscal_result.success,
                'receipt_number': fiscal_result.receipt_number,
                'error': fiscal_result.error,
                'retryable': fiscal_result.retryable,
                'pending_manual': fiscal_result.pending_manual,
            }
        return data

    @action(detail=True, methods=['post'])
    def add_line(self, request, pk=None):
        sale = self.get_object()
        serializer = AddLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale.add_product(**serializer.validated_data)
        return Response(self._respond(sale))

    @action(detail=True, methods=['post'])
    def remove_line(self, request, pk=None):
        sale = self.get_object()
        product = Product.objects.filter(pk=request.data.get('product')).first()
        if product is None:
            raise SaleError('Unknown product.')
        sale.remove_product(product)
        return Response(self._respond(sale))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Discards a cart that was never completed. Nothing was deducted
        from stock yet, so there's nothing to reverse."""
        sale = self.get_object()
        if sale.status != Sale.Status.OPEN:
            raise SaleError('Only an unfinished sale can be cancelled. Void a completed sale instead.')
        sale.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        sale = self.get_object()
        features.require('pos_sale', store=sale.store)
        serializer = CompleteSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = sale.complete(user=request.user, **_payment(serializer.validated_data, request, sale.store))
        _audit_discount(request, sale)
        return Response(self._respond(sale, result))

    @action(detail=False, methods=['post'], url_path='record')
    def record_sale(self, request):
        """POST /sales/record/: a whole sale the till rang up itself —
        offline, or just now from its own copy of the catalog (see
        Sale.record_offline). The till's own id makes this safe to resend:
        a sale already recorded comes back as it is (200), a new one 201."""
        serializer = OfflineSaleSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        existing = self._recorded(data['id'])
        if existing is not None:
            return Response(self._respond(existing))
        features.require('pos_sale', store=data['store'])
        data = _payment(data, request, data['store'])
        try:
            sale, result, price_changes = Sale.record_offline(user=request.user, **data)
        except IntegrityError:
            # The same sale sent twice at once (two tabs syncing): the
            # other request recorded it.
            existing = self._recorded(data['id'])
            if existing is None:
                raise
            return Response(self._respond(existing))
        if price_changes:
            changes = '; '.join(f'{c["product"]} charged {c["charged"]:,.0f}, price now {c["current"]:,.0f}'
                                for c in price_changes)
            record(Action.OFFLINE_SALE_PRICE, f'Sale #{sale.number} was made offline at old prices: {changes}',
                   request=request, store=sale.store, data={'sale': str(sale.id), 'changes': price_changes})
        _audit_discount(request, sale)
        return Response(self._respond(sale, result), status=status.HTTP_201_CREATED)

    def _recorded(self, sale_id):
        """The sale with this id if it's already recorded; refuses an id
        that belongs to someone else's sale or a cart still open online."""
        sale = Sale.objects.filter(pk=sale_id).first()
        if sale is None:
            return None
        if not self.get_queryset().filter(pk=sale_id).exists() or sale.status == Sale.Status.OPEN:
            raise SaleError('This sale id is already in use.')
        return self.get_queryset().get(pk=sale_id)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        sale = self.get_object()
        result = sale.retry_fiscal()
        return Response(self._respond(sale, result))

    @action(detail=True, methods=['post'])
    def record_fiscal(self, request, pk=None):
        """The cashier types in the receipt number printed by the store's
        standalone EFD machine (see fiscal.drivers.manual_efd)."""
        sale = self.get_object()
        serializer = RecordFiscalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale.record_fiscal_receipt(receipt_number=serializer.validated_data['receipt_number'], user=request.user)
        return Response(self._respond(sale))

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """A manager voids directly. Anyone else needs a manager to enter
        their own username and password at the till as approval — the
        'manager override' every real POS has."""
        sale = self.get_object()
        serializer = VoidSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if is_store_manager(request.user, sale.store):
            approver = request.user
        else:
            approver = _manager_override(request, data['approver_username'], data['approver_password'], sale.store)
            if approver is None:
                raise PermissionDenied('A store manager must approve this void.')
        sale.void(user=request.user, approver=approver, reason=data['reason'])
        record(Action.SALE_VOIDED, f'Sale #{sale.number} ({sale.total:,.0f}) voided: {data["reason"]}',
               request=request, store=sale.store,
               data={'sale': str(sale.id), 'approved_by': approver.username, 'efd_receipt_no': sale.efd_receipt_no})
        return Response(self._respond(sale))


class TillSnapshotView(APIView):
    """GET /api/pos/till/?store=<id>: everything the till needs to keep
    selling with no connection — the catalog, this store's prices for
    today (a running promotion's price where there is one), sellable
    stock, payment methods, credit customers with what they owe, and the
    caller's open shift. The till refreshes it whenever it's online and
    records what it sells against it (POST /sales/record/)."""

    def get(self, request):
        store = Store.objects.filter(pk=request.query_params.get('store')).select_related('entity').first()
        allowed = accessible_store_ids(request.user)
        if store is None or (not request.user.is_superuser and store.entity_id != request.user.entity_id) \
                or (allowed is not None and store.pk not in set(allowed)):
            raise NotFound('Store not found.')
        entity = store.entity
        products = Product.objects.filter(entity=entity).select_related('uom', 'category')
        price_store = store if entity.price_mode == Entity.PriceMode.STORE else None
        prices = {(p.product_id, p.uom_id): {'unit_price': p.unit_price, 'regular_price': p.unit_price, 'promotion': None}
                  for p in Price.objects.filter(entity=entity, store=price_store)}
        # Store-level promotions come first, so they win over firm-wide ones.
        for promo in reversed(list(Promotion.running(store=store))):
            row = prices.setdefault((promo.product_id, promo.uom_id), {'regular_price': None})
            row.update(unit_price=promo.promo_price, promotion=promo.name)
        batches = sellable_batches(StockBatch.objects.filter(store=store))
        shift = Shift.objects.filter(store=store, cashier=request.user, closed_at__isnull=True).first()
        customers = (with_balances(Customer.objects.filter(entity=entity, is_active=True))
                     if features.is_enabled('customer_credit', store=store) else Customer.objects.none())
        shift_data = None
        if shift is not None:
            shift_data = {**ShiftSerializer(shift).data, 'summary': shift.summary()}
        return Response({
            'store': str(store.pk),
            'store_details': {'id': str(store.pk), 'name': store.name, 'address': store.address, 'tin': store.tin},
            'generated_at': timezone.now(),
            'cashier_discount_limit': entity.cashier_discount_limit,
            'products': [{
                'id': str(p.pk), 'name': p.name, 'short_name': p.short_name, 'brand': p.brand, 'size': p.size,
                'barcode': p.barcode, 'category_name': p.category.name if p.category_id else '',
                'uom': str(p.uom_id), 'vat_class': p.vat_class, 'tracks_expiry': p.tracks_expiry,
            } for p in products],
            'units': UnitOfMeasureSerializer(UnitOfMeasure.objects.filter(entity=entity), many=True).data,
            'prices': [{'product': str(product), 'uom': str(uom) if uom else None, **row}
                       for (product, uom), row in prices.items()],
            'stock': [{'product': str(b.product_id), 'qty_on_hand': b.qty_on_hand, 'expiry_date': b.expiry_date}
                      for b in batches],
            'payment_methods': PaymentMethodSerializer(PaymentMethod.active_for(entity), many=True,
                                                       context={'entity': entity}).data,
            'customers': [{'id': str(c.pk), 'name': c.name, 'phone': c.phone, 'owing': c.owing,
                           'credit_limit': c.credit_limit} for c in customers],
            'shift': shift_data,
        })


class ShiftViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """POST /shifts/ {store, opening_float} opens the caller's shift.
    GET /shifts/current/?store=<id> returns the caller's open shift there
    (or null). POST .../close/ {counted_cash, note} closes it and returns
    the Z-report."""

    queryset = Shift.objects.select_related('store', 'cashier').all()
    serializer_class = ShiftSerializer
    filterset_fields = ['store', 'cashier']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_POS_ROLES)]
    http_method_names = ['get', 'post', 'head', 'options']

    def perform_create(self, serializer):
        store = serializer.validated_data['store']
        features.require('pos_sale', store=store)
        if Shift.objects.filter(store=store, cashier=self.request.user, closed_at__isnull=True).exists():
            raise SaleError('You already have an open shift at this store.')
        serializer.save(cashier=self.request.user)

    def _with_summary(self, shift):
        data = self.get_serializer(shift).data
        data['summary'] = shift.summary()
        return data

    def retrieve(self, request, *args, **kwargs):
        return Response(self._with_summary(self.get_object()))

    @action(detail=False, methods=['get'])
    def current(self, request):
        shift = self.get_queryset().filter(
            store_id=request.query_params.get('store'), cashier=request.user, closed_at__isnull=True,
        ).first() if request.query_params.get('store') else None
        return Response(self._with_summary(shift) if shift else None)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        shift = self.get_object()
        if shift.cashier_id != request.user.id and not is_store_manager(request.user, shift.store):
            raise PermissionDenied('Only the shift\'s own cashier or a store manager can close it.')
        serializer = CloseShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shift.close(counted_cash=serializer.validated_data['counted_cash'], note=serializer.validated_data['note'])
        z = shift.summary()
        record(Action.SHIFT_CLOSED,
               f'Shift of {shift.cashier.username} closed: {z["sales_count"]} sales, difference {z["variance"]:,.0f}',
               request=request, store=shift.store,
               data={'shift': str(shift.id), 'expected_cash': z['expected_cash'], 'counted_cash': z['counted_cash'],
                     'variance': z['variance']})
        return Response(self._with_summary(shift))
