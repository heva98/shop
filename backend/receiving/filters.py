import django_filters

from .models import ReceivingInvoice


class ReceivingInvoiceFilter(django_filters.FilterSet):
    received_date_after = django_filters.DateFilter(field_name='received_date', lookup_expr='gte')
    received_date_before = django_filters.DateFilter(field_name='received_date', lookup_expr='lte')
    invoice_number = django_filters.CharFilter(field_name='invoice_number', lookup_expr='icontains')

    class Meta:
        model = ReceivingInvoice
        fields = ['store', 'supplier', 'status', 'invoice_number', 'received_date_after', 'received_date_before']
