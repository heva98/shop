from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied

from audit.services import Action, record
from core.models import Role
from core.permissions import write_roles

from .models import EntityPaymentMethod, PaymentMethod
from .serializers import PaymentMethodSerializer


class PaymentMethodViewSet(viewsets.ModelViewSet):
    """PaymentMethod rows are global (no entity FK — see the model), same
    as core.ModuleRegistry, so every firm lists the same ones. Switching
    one on or off is per firm: an entity_admin's PATCH writes their own
    firm's EntityPaymentMethod, never the shared row. Only a superuser
    with no firm of their own changes the platform default."""
    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [write_roles(Role.ENTITY_ADMIN)]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_serializer_context(self):
        return {**super().get_serializer_context(), 'entity': self.request.user.entity}

    def perform_update(self, serializer):
        method = serializer.instance
        entity = self.request.user.entity
        if 'is_active' not in serializer.validated_data:
            return
        on = serializer.validated_data['is_active']
        if entity is None:
            if not self.request.user.is_superuser:
                raise PermissionDenied('You are not assigned to a shop.')
            if method.is_active != on:
                method.is_active = on
                method.save(update_fields=['is_active'])
                record(Action.PAYMENT_METHOD_CHANGED,
                       f'{method.name} switched {"on" if on else "off"} by default for all shops', request=self.request)
            return
        if method.is_active_for(entity) != on:
            EntityPaymentMethod.objects.update_or_create(entity=entity, method=method, defaults={'is_active': on})
            record(Action.PAYMENT_METHOD_CHANGED, f'{method.name} switched {"on" if on else "off"}',
                   request=self.request, entity=entity)
