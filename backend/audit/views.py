from django_filters import rest_framework as filters
from rest_framework import serializers, viewsets

from core.models import Role
from core.permissions import roles
from core.queryset_scoping import accessible_store_ids

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source='get_action_display', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True, default='')

    class Meta:
        model = AuditEvent
        fields = ['id', 'created_at', 'username', 'action', 'action_label', 'summary', 'store', 'store_name',
                  'data', 'ip_address']
        read_only_fields = fields


class AuditEventFilter(filters.FilterSet):
    start = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    end = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = AuditEvent
        fields = ['action', 'store', 'username', 'start', 'end']


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    """Entity admins see their whole firm's log; store managers see only
    events at their own stores. Nobody can write here."""
    queryset = AuditEvent.objects.select_related('store').all()
    serializer_class = AuditEventSerializer
    filterset_class = AuditEventFilter
    search_fields = ['username', 'summary']
    permission_classes = [roles(Role.STORE_MANAGER, Role.ENTITY_ADMIN)]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        qs = qs.filter(entity_id=user.entity_id)
        store_ids = accessible_store_ids(user)
        if store_ids is not None:
            qs = qs.filter(store_id__in=list(store_ids))
        return qs
