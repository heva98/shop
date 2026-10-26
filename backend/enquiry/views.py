from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import Action, record
from core import features
from core.models import Role
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin, accessible_store_ids

from .models import Enquiry, Transfer
from .serializers import (
    CancelTransferSerializer, ConfirmReceiptSerializer, EnquirySerializer, ResolveSerializer,
    TransferCreateSerializer, TransferPaymentSerializer, TransferSerializer,
)

_ENQUIRY_ROLES = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)


def _acts_for(user, store):
    """Whether `user` may act as `store` — holds a role there, or is
    entity-wide (entity_admin, superuser)."""
    ids = accessible_store_ids(user)
    return ids is None or store.id in list(ids)


def _lines(transfer):
    return ', '.join(f'{line.batch.product.name} x{line.qty.normalize():f}' for line in transfer.lines.select_related('batch__product'))


class EnquiryViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Deliberately entity-scoped only, not store-scoped: a broadcast
    enquiry (architecture.txt §1 — "any capable store opts in") has to be
    readable by every store in the firm, not just the requesting/target
    store, or no other store could ever see it to respond. The actual
    security boundary — which store you're allowed to act *as* — is
    enforced where it matters: EnquirySerializer.validate_requesting_store
    on create, and the fulfilling store check in fulfill()."""
    queryset = (Enquiry.objects.select_related('requesting_store', 'target_store', 'created_by')
                .prefetch_related('lines__product__uom').all())
    serializer_class = EnquirySerializer
    filterset_fields = ['requesting_store', 'target_store', 'mode', 'status']
    entity_field = 'requesting_store__entity_id'
    permission_classes = [write_roles(*_ENQUIRY_ROLES)]
    http_method_names = ['get', 'post', 'head', 'options']

    def perform_create(self, serializer):
        features.require('transfer', entity=serializer.validated_data['requesting_store'].entity_id)
        serializer.save(created_by=self.request.user)

    def _open(self):
        enquiry = self.get_object()
        if enquiry.status != Enquiry.Status.OPEN:
            raise ValidationError(f'This enquiry is already {enquiry.get_status_display().lower()}.')
        return enquiry

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """The main store turning down a branch's request (hub mode). A
        broadcast enquiry can't be rejected — another store may still
        help; it stays open until fulfilled or cancelled."""
        enquiry = self._open()
        if enquiry.mode != Enquiry.Mode.HUB or not _acts_for(request.user, enquiry.target_store):
            raise PermissionDenied('Only the main store can turn down this enquiry.')
        enquiry.status = Enquiry.Status.REJECTED
        enquiry.save(update_fields=['status'])
        return Response(self.get_serializer(enquiry).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """The requesting store withdrawing its own open enquiry."""
        enquiry = self._open()
        if not _acts_for(request.user, enquiry.requesting_store):
            raise PermissionDenied('Only the store that asked can cancel this enquiry.')
        enquiry.status = Enquiry.Status.CANCELLED
        enquiry.save(update_fields=['status'])
        return Response(self.get_serializer(enquiry).data)

    @action(detail=True, methods=['post'])
    def fulfill(self, request, pk=None):
        """Respond & fulfil: sends the stock (all or part of what was asked
        for) as one transfer and closes the enquiry.
        Body: {"from_store": "<uuid>", "note": "...",
               "lines": [{"product": "<uuid>", "qty": n} | {"batch": "<uuid>", "qty": n}, ...]}.
        """
        enquiry = self._open()
        serializer = TransferCreateSerializer(
            data={**request.data, 'to_store': str(enquiry.requesting_store_id)},
            context=self.get_serializer_context(),
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if enquiry.mode == Enquiry.Mode.HUB and data['from_store'].id != enquiry.target_store_id:
            raise ValidationError('This enquiry is for the main store to fulfil.')
        transfer = Transfer.send(
            from_store=data['from_store'], to_store=enquiry.requesting_store, items=data['lines'],
            user=request.user, enquiry=enquiry, note=data['note'],
        )
        enquiry.status = Enquiry.Status.FULFILLED
        enquiry.save(update_fields=['status'])
        record(Action.TRANSFER_SENT,
               f'Transfer #{transfer.number} to {transfer.to_store.name} (for their enquiry): {_lines(transfer)}',
               request=request, store=transfer.from_store, data={'transfer': str(transfer.id)})
        return Response({
            'enquiry': self.get_serializer(enquiry).data,
            'transfer': TransferSerializer(transfer).data,
        })


class TransferViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """POST /transfers/ {from_store, to_store, note, lines} sends stock
    straight away. After that a transfer only moves through its actions:
    confirm_receipt (receiving store), resolve (a short delivery, either
    store's manager), cancel (sender, before receipt) and pay (hub mode,
    the main store records the branch's payment)."""

    queryset = (Transfer.objects.select_related(
        'from_store', 'to_store', 'enquiry', 'dispatched_by', 'received_by', 'payment_method')
        .prefetch_related('lines__batch__product__uom').all())
    serializer_class = TransferSerializer
    filterset_fields = ['from_store', 'to_store', 'mode', 'status']
    entity_field = 'from_store__entity_id'
    store_fields = ('from_store_id', 'to_store_id')
    permission_classes = [write_roles(*_ENQUIRY_ROLES)]

    def create(self, request, *args, **kwargs):
        serializer = TransferCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        transfer = Transfer.send(
            from_store=data['from_store'], to_store=data['to_store'], items=data['lines'],
            user=request.user, note=data['note'],
        )
        record(Action.TRANSFER_SENT, f'Transfer #{transfer.number} to {transfer.to_store.name}: {_lines(transfer)}',
               request=request, store=transfer.from_store, data={'transfer': str(transfer.id)})
        return Response(self._fresh(transfer), status=status.HTTP_201_CREATED)

    def _fresh(self, transfer):
        return self.get_serializer(self.get_queryset().get(pk=transfer.pk)).data

    @action(detail=True, methods=['post'])
    def confirm_receipt(self, request, pk=None):
        transfer = self.get_object()
        if not _acts_for(request.user, transfer.to_store):
            raise PermissionDenied(f'Only {transfer.to_store.name} can confirm what it received.')
        serializer = ConfirmReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer.confirm_receipt(user=request.user, **serializer.validated_data)
        short = transfer.status == Transfer.Status.DISCREPANCY
        record(Action.TRANSFER_RECEIVED,
               f'Transfer #{transfer.number} from {transfer.from_store.name} received'
               + (f' short: {transfer.discrepancy_note}' if short else ' in full'),
               request=request, store=transfer.to_store, data={'transfer': str(transfer.id), 'short': short})
        return Response(self._fresh(transfer))

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        transfer = self.get_object()
        if not (is_store_manager(request.user, transfer.from_store) or is_store_manager(request.user, transfer.to_store)):
            raise PermissionDenied('A manager of either store must resolve a short delivery.')
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer.resolve(user=request.user, **serializer.validated_data)
        record(Action.TRANSFER_RESOLVED,
               f'Short delivery on transfer #{transfer.number} resolved: {transfer.get_resolution_display()}',
               request=request, store=transfer.from_store, data={'transfer': str(transfer.id)})
        return Response(self._fresh(transfer))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        transfer = self.get_object()
        if not _acts_for(request.user, transfer.from_store):
            raise PermissionDenied(f'Only {transfer.from_store.name} can cancel a transfer it sent.')
        serializer = CancelTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer.cancel(user=request.user, reason=serializer.validated_data['reason'])
        record(Action.TRANSFER_CANCELLED, f'Transfer #{transfer.number} to {transfer.to_store.name} cancelled',
               request=request, store=transfer.from_store, data={'transfer': str(transfer.id)})
        return Response(self._fresh(transfer))

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        transfer = self.get_object()
        if not is_store_manager(request.user, transfer.from_store):
            raise PermissionDenied('A manager of the main store records branch payments.')
        serializer = TransferPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer.record_payment(**serializer.validated_data)
        record(Action.TRANSFER_PAID,
               f'{transfer.to_store.name} paid {transfer.amount:,.0f} for transfer #{transfer.number} '
               f'({transfer.payment_method.name})',
               request=request, store=transfer.from_store,
               data={'transfer': str(transfer.id), 'amount': transfer.amount, 'reference': transfer.payment_reference})
        return Response(self._fresh(transfer))
