from decimal import Decimal

import django_filters
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import Action, record
from core.models import Role, StoreRole
from core.permissions import is_store_manager, write_roles
from core.queryset_scoping import TenantScopedQuerySetMixin

from .models import Customer, CustomerPayment, with_balances
from .serializers import (
    CustomerPaymentSerializer, CustomerSerializer, ReceivePaymentSerializer, VoidPaymentSerializer,
)

_TILL_ROLES = (Role.CASHIER, Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)
_MANAGERS = (Role.STORE_MANAGER, Role.ENTITY_ADMIN)


def _is_any_manager(user):
    return user.is_superuser or StoreRole.objects.filter(user=user, role__in=_MANAGERS).exists()


class CustomerFilter(django_filters.FilterSet):
    owing = django_filters.BooleanFilter(method='filter_owing')

    class Meta:
        model = Customer
        fields = ['is_active', 'owing']

    def filter_owing(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(owing__gt=0) if value else queryset.filter(owing__lte=0)


class CustomerViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """The shop's credit customers, each with what they owe. Anyone at the
    till can register a customer (so a sale can be put on their account),
    but only a manager decides how much credit they get: a customer added
    by anyone else starts with a credit limit of 0."""
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    filterset_class = CustomerFilter
    search_fields = ['name', 'phone']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_TILL_ROLES)]

    def get_queryset(self):
        return with_balances(super().get_queryset())

    def perform_create(self, serializer):
        user = self.request.user
        if user.entity_id is None:
            raise ValidationError('Your account is not linked to a shop.')
        extra = {} if _is_any_manager(user) else {'credit_limit': Decimal('0')}
        customer = serializer.save(entity=user.entity, **extra)
        record(Action.CUSTOMER_CHANGED, f'Customer {customer.name} added', request=self.request,
               data={'credit_limit': customer.credit_limit})

    def perform_update(self, serializer):
        old_limit = serializer.instance.credit_limit
        if 'credit_limit' in serializer.validated_data and serializer.validated_data['credit_limit'] != old_limit \
                and not _is_any_manager(self.request.user):
            raise PermissionDenied('Only a manager can change a customer\'s credit limit.')
        customer = serializer.save()
        record(Action.CUSTOMER_CHANGED, f'Customer {customer.name} changed', request=self.request,
               data={'old_credit_limit': old_limit, 'credit_limit': customer.credit_limit})

    def perform_destroy(self, instance):
        if instance.sales.exists() or instance.payments.exists():
            raise PermissionDenied(f'{instance.name} has sales or payments, so they cannot be removed. Deactivate them instead.')
        if not _is_any_manager(self.request.user):
            raise PermissionDenied('Only a manager can remove a customer.')
        record(Action.CUSTOMER_CHANGED, f'Customer {instance.name} removed', request=self.request)
        instance.delete()

    @action(detail=False, methods=['get'])
    def summary(self, request):
        customers = list(self.get_queryset().filter(is_active=True))
        owing = [c for c in customers if c.owing > 0]
        over = [c for c in owing if c.credit_limit is not None and c.owing > c.credit_limit]
        return Response({
            'owed': sum((c.owing for c in owing), Decimal('0')),
            'customers_owing': len(owing),
            'over_limit': len(over),
            'customers': len(customers),
        })

    @action(detail=True, methods=['get'])
    def statement(self, request, pk=None):
        """Every credit sale and payment for this customer, oldest first,
        with the running balance — what to show (or print) when they come
        to settle up."""
        customer = self.get_object()
        from pos.models import Sale

        rows = []
        sales = (customer.sales.filter(status__in=[Sale.Status.COMPLETED, Sale.Status.VOIDED], credit_amount__gt=0)
                 .select_related('store'))
        for sale in sales:
            rows.append({
                'kind': 'sale', 'id': str(sale.id), 'date': sale.completed_at, 'store': sale.store.name,
                'description': f'Receipt #{sale.number}', 'amount': sale.credit_amount,
                'voided': sale.status == Sale.Status.VOIDED,
            })
        for payment in customer.payments.select_related('store', 'payment_method'):
            rows.append({
                'kind': 'payment', 'id': str(payment.id), 'date': payment.created_at, 'store': payment.store.name,
                'description': f'Paid by {payment.payment_method.name}'
                               + (f' ({payment.reference})' if payment.reference else ''),
                'amount': -payment.amount, 'voided': payment.voided_at is not None,
            })
        rows.sort(key=lambda r: r['date'] or timezone.now())
        balance = Decimal('0')
        for row in rows:
            if not row['voided']:
                balance += row['amount']
            row['balance'] = balance
        return Response({'customer': self.get_serializer(customer).data, 'rows': rows, 'owing': balance})


class PaymentFilter(django_filters.FilterSet):
    start = django_filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    end = django_filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = CustomerPayment
        fields = ['customer', 'store', 'shift', 'start', 'end']


class CustomerPaymentViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """POST /payments/ {customer, store, amount, payment_method, reference,
    note} records a repayment; POST .../void/ {reason} reverses one
    (managers only). Payments are never edited or deleted."""
    queryset = CustomerPayment.objects.select_related(
        'customer', 'store', 'payment_method', 'received_by', 'voided_by').all()
    serializer_class = CustomerPaymentSerializer
    filterset_class = PaymentFilter
    search_fields = ['customer__name', 'customer__phone', 'reference']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [write_roles(*_TILL_ROLES)]

    def create(self, request):
        serializer = ReceivePaymentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment = CustomerPayment.receive(user=request.user, **serializer.validated_data)
        record(Action.CREDIT_PAYMENT, f'{payment.customer.name} paid {payment.amount:,.0f} by {payment.payment_method.name}',
               request=request, store=payment.store,
               data={'customer': str(payment.customer_id), 'amount': payment.amount, 'reference': payment.reference})
        return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        payment = self.get_object()
        if not is_store_manager(request.user, payment.store):
            raise PermissionDenied(f'Only a manager of {payment.store.name} can void a payment.')
        serializer = VoidPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment.void(user=request.user, reason=serializer.validated_data['reason'])
        record(Action.CREDIT_PAYMENT_VOIDED,
               f'Payment of {payment.amount:,.0f} from {payment.customer.name} voided: {payment.void_reason}',
               request=request, store=payment.store, data={'payment': str(payment.id)})
        return Response(self.get_serializer(payment).data)
