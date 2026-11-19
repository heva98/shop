"""HTTP adapters for selling: parse and validate the request, check who
may do it, call one use case in pos.services, log it (pos.audit) and
shape the response. No selling rule lives here."""

from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.utils.translation import gettext
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.services import Summary
from catalog.models import Product
from core import features
from core.login_guard import normalize_username, record_failure, refuse_if_locked
from core.models import Role, Store
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin, can_access_store

from . import audit, till
from .models import Sale, SaleError, Shift
from .serializers import (
    AddLineSerializer, CloseShiftSerializer, CompleteSaleSerializer, OfflineSaleSerializer, RecordFiscalSerializer,
    SaleSerializer, ShiftSerializer, VoidSaleSerializer,
)
from .services import cart, checkout, fiscal, shifts

_POS_ROLES = (Role.CASHIER, Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)


def _manager_override(request, username, password, store):
    """The manager who typed their own username and password at the till
    to approve something (a void, a large discount), or None when nobody
    did. Wrong details are refused rather than ignored.

    A wrong password here counts toward the same limits as one at
    sign-in (core.login_guard): otherwise a cashier could guess a
    manager's or owner's password through this box without ever being
    locked out or showing in the activity log."""
    if not username or not password:
        return None
    username = normalize_username(username)
    refuse_if_locked(request, username)
    approver = authenticate(request, username=username, password=password)
    if approver is None:
        record_failure(request, username, Summary(
            'Wrong password for "{username}" in a manager approval at {store}', username=username, store=store.name))
    if approver is None or not is_store_manager(approver, store):
        raise PermissionDenied(gettext('Approval failed: wrong username/password, or that user is not a manager at this store.'))
    return approver


def _payment(data, request, store):
    """The keyword arguments checkout.complete takes, from a validated
    CompleteSaleSerializer / OfflineSaleSerializer payload."""
    data = dict(data)
    username, password = data.pop('approver_username', ''), data.pop('approver_password', '')
    data['discount_approver'] = _manager_override(request, username, password, store)
    return data


def _fiscal_result(result):
    return {
        'success': result.success,
        'receipt_number': result.receipt_number,
        'error': result.error,
        'retryable': result.retryable,
        'pending_manual': result.pending_manual,
    }


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
        data = self.get_serializer(self.get_queryset().get(pk=sale.pk)).data
        if fiscal_result is not None:
            data['fiscal_result'] = _fiscal_result(fiscal_result)
        return data

    @action(detail=True, methods=['post'])
    def add_line(self, request, pk=None):
        sale = self.get_object()
        serializer = AddLineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart.add_product(sale, **serializer.validated_data)
        return Response(self._respond(sale))

    @action(detail=True, methods=['post'])
    def remove_line(self, request, pk=None):
        sale = self.get_object()
        product = Product.objects.filter(pk=request.data.get('product')).first()
        if product is None:
            raise SaleError(gettext('Unknown product.'))
        cart.remove_product(sale, product)
        return Response(self._respond(sale))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        cart.cancel(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        sale = self.get_object()
        features.require('pos_sale', store=sale.store)
        serializer = CompleteSaleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = checkout.complete(sale, user=request.user, **_payment(serializer.validated_data, request, sale.store))
        audit.discount(request, sale)
        return Response(self._respond(sale, result))

    @action(detail=False, methods=['post'], url_path='record')
    def record_sale(self, request):
        """POST /sales/record/: a whole sale the till rang up itself —
        offline, or just now from its own copy of the catalog (see
        checkout.record_offline). The till's own id makes this safe to
        resend: a sale already recorded comes back as it is (200), a new
        one 201."""
        serializer = OfflineSaleSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        existing = self._recorded(data['id'])
        if existing is not None:
            return Response(self._respond(existing))
        features.require('pos_sale', store=data['store'])
        dated = data.get('completed_at')
        data = _payment(data, request, data['store'])
        try:
            sale, result, price_changes = checkout.record_offline(user=request.user, **data)
        except IntegrityError:
            # The same sale sent twice at once (two tabs syncing): the
            # other request recorded it.
            existing = self._recorded(data['id'])
            if existing is None:
                raise
            return Response(self._respond(existing))
        audit.offline_prices(request, sale, price_changes)
        audit.unrecorded_stock(request, sale)
        audit.discount(request, sale)
        if not data.get('strict'):
            audit.offline_limits(request, sale, dated)
        return Response(self._respond(sale, result), status=status.HTTP_201_CREATED)

    def _recorded(self, sale_id):
        """The sale with this id if it's already recorded; refuses an id
        that belongs to someone else's sale or a cart still open online."""
        sale = Sale.objects.filter(pk=sale_id).first()
        if sale is None:
            return None
        if not self.get_queryset().filter(pk=sale_id).exists() or sale.status == Sale.Status.OPEN:
            raise SaleError(gettext('This sale id is already in use.'))
        return self.get_queryset().get(pk=sale_id)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        sale = self.get_object()
        return Response(self._respond(sale, fiscal.fiscalize(sale)))

    @action(detail=True, methods=['post'])
    def record_fiscal(self, request, pk=None):
        """The cashier types in the receipt number printed by the store's
        standalone EFD machine (see fiscal.drivers.manual_efd)."""
        sale = self.get_object()
        serializer = RecordFiscalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fiscal.record_receipt(sale, receipt_number=serializer.validated_data['receipt_number'], user=request.user)
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
                raise PermissionDenied(gettext('A store manager must approve this void.'))
        checkout.void(sale, user=request.user, approver=approver, reason=data['reason'])
        audit.voided(request, sale, approver, data['reason'])
        return Response(self._respond(sale))


class TillSnapshotView(APIView):
    """GET /api/pos/till/?store=<id>[&catalog=<version>][&sync=<state>]:
    everything the till needs to keep selling offline (see pos.till)."""

    def get(self, request):
        store = Store.objects.filter(pk=request.query_params.get('store')).select_related('entity').first()
        if store is None or not can_access_store(request.user, store):
            raise NotFound(gettext('Store not found.'))
        return Response(till.snapshot(store, request.user, catalog_held=request.query_params.get('catalog'),
                                      sync_held=request.query_params.get('sync')))


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
        shifts.check_can_open(store, self.request.user)
        serializer.save(cashier=self.request.user)

    def _with_summary(self, shift, summary=None):
        data = self.get_serializer(shift).data
        data['summary'] = shifts.summary(shift) if summary is None else summary
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
            raise PermissionDenied(gettext("Only the shift's own cashier or a store manager can close it."))
        serializer = CloseShiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        z = shifts.close(shift, counted_cash=serializer.validated_data['counted_cash'],
                         note=serializer.validated_data['note'])
        audit.shift_closed(request, shift, z)
        return Response(self._with_summary(shift, z))
