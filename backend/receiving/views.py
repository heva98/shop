from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import Action, record
from core import features
from core.models import Role
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin

from .filters import ReceivingInvoiceFilter
from .models import ReceivingInvoice, ReceivingInvoiceLine, Supplier
from .serializers import (
    ReceivingInvoiceLineSerializer, ReceivingInvoiceSerializer, SupplierPaymentSerializer, SupplierSerializer,
)

_RECEIVING_ROLES = (Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)


class SupplierViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.select_related('entity').all()
    serializer_class = SupplierSerializer
    entity_field = 'entity_id'
    search_fields = ['name']
    permission_classes = [write_roles(*_RECEIVING_ROLES)]


class ReceivingInvoiceViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Draft -> Received state machine (see ReceivingInvoice.mark_received).
    Save as draft = a normal create/update with status left at 'draft'.
    Save and receive = create/update, then POST .../receive/."""

    queryset = (ReceivingInvoice.objects.select_related('store', 'supplier')
                .prefetch_related('lines', 'payments__recorded_by').all())
    serializer_class = ReceivingInvoiceSerializer
    filterset_class = ReceivingInvoiceFilter
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_RECEIVING_ROLES)]

    def perform_create(self, serializer):
        features.require('receiving_invoice', store=serializer.validated_data['store'])
        serializer.save()

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        invoice = self.get_object()
        features.require('receiving_invoice', store=invoice.store)
        invoice.mark_received()
        record(Action.INVOICE_RECEIVED, f'Invoice {invoice.invoice_number} from {invoice.supplier.name} received',
               request=request, store=invoice.store, data={'invoice': str(invoice.id)})
        return Response(self.get_serializer(invoice).data)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        """Records money paid to the supplier against this invoice:
        {amount, paid_on, method, reference}. Store managers and admins
        only — paying suppliers is a finance job."""
        invoice = self.get_object()
        if not is_store_manager(request.user, invoice.store):
            raise PermissionDenied('Only a manager of this store can record supplier payments.')
        serializer = SupplierPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = invoice.record_payment(
            amount=data['amount'], paid_on=data['paid_on'], method=data['method'],
            reference=data.get('reference', ''), user=request.user,
        )
        record(Action.SUPPLIER_PAYMENT,
               f'Paid {payment.amount:,.0f} to {invoice.supplier.name} for invoice {invoice.invoice_number} '
               f'({payment.get_method_display()})',
               request=request, store=invoice.store,
               data={'invoice': str(invoice.id), 'amount': payment.amount, 'reference': payment.reference})
        return Response(self.get_serializer(self.get_queryset().get(pk=invoice.pk)).data)


class ReceivingInvoiceLineViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Exposed separately (not just nested under ReceivingInvoiceSerializer)
    so a draft invoice can have lines appended one at a time when a cashier
    resumes it later — ReceivingInvoiceSerializer's nested `lines` only
    handles the all-at-once shape on create."""
    queryset = ReceivingInvoiceLine.objects.select_related('invoice__store', 'product', 'uom').all()
    serializer_class = ReceivingInvoiceLineSerializer
    filterset_fields = ['invoice']
    entity_field = 'invoice__store__entity_id'
    store_fields = ('invoice__store_id',)
    permission_classes = [write_roles(*_RECEIVING_ROLES)]

    def perform_create(self, serializer):
        invoice = serializer.validated_data['invoice']
        if invoice.status != ReceivingInvoice.Status.DRAFT:
            raise ValidationError('Cannot add lines to an invoice that has already been received.')
        serializer.save()

    def perform_update(self, serializer):
        invoice = serializer.instance.invoice
        if invoice.status != ReceivingInvoice.Status.DRAFT:
            raise ValidationError('Cannot edit lines on an invoice that has already been received.')
        serializer.save()

    def perform_destroy(self, instance):
        if instance.invoice.status != ReceivingInvoice.Status.DRAFT:
            raise ValidationError('Cannot remove lines from an invoice that has already been received.')
        instance.delete()
