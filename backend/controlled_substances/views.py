from django_filters import rest_framework as filters
from rest_framework import viewsets

from core.models import Role
from core.permissions import roles
from core.queryset_scoping import TenantScopedQuerySetMixin

from .models import ControlledSubstanceEntry
from .serializers import ControlledSubstanceEntrySerializer


class EntryFilter(filters.FilterSet):
    start = filters.DateFilter(field_name='recorded_at', lookup_expr='date__gte')
    end = filters.DateFilter(field_name='recorded_at', lookup_expr='date__lte')

    class Meta:
        model = ControlledSubstanceEntry
        fields = ['store', 'product', 'start', 'end']


class ControlledSubstanceEntryViewSet(TenantScopedQuerySetMixin, viewsets.ReadOnlyModelViewSet):
    """GET /api/controlled-substances/entries/?store=&product=&start=&end=

    Read-only: rows are written by pos.Sale. Unlike most screens, reading
    is limited too: it is a regulated record with patients' names, so only
    pharmacists (the storekeeper role), managers and owners see it."""
    queryset = ControlledSubstanceEntry.objects.select_related('store', 'product__uom', 'sale', 'dispensed_by')
    serializer_class = ControlledSubstanceEntrySerializer
    filterset_class = EntryFilter
    search_fields = ['patient_name', 'prescriber_name', 'prescription_ref', 'product__name']
    entity_field = 'store__entity_id'
    store_fields = ('store_id',)
    permission_classes = [roles(Role.STOREKEEPER, Role.STORE_MANAGER, Role.ENTITY_ADMIN)]
