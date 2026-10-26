from rest_framework import viewsets

from audit.services import Action, record
from core.models import Role
from core.permissions import write_roles

from .models import PaymentMethod
from .serializers import PaymentMethodSerializer


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """PaymentMethod rows are global (no entity FK — see the model), same
    as core.ModuleRegistry, so there's no tenant scoping to apply here.
    Settings-scoped in the frontend (NAV_DEFS in appData.js), so writes
    require entity_admin even though the rows themselves aren't
    entity-owned."""
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [write_roles(Role.ENTITY_ADMIN)]

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        method = serializer.save()
        if method.is_active != was_active:
            record(Action.PAYMENT_METHOD_CHANGED, f'{method.name} switched {"on" if method.is_active else "off"}',
                   request=self.request)
