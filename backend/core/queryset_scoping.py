from django.db.models import Q

from .models import Role, StoreRole


def accessible_store_ids(user):
    """Store ids `user` may act on.

    Returns None to mean "every store in the user's entity" — granted to
    Django superusers and to entity_admin StoreRole holders, whose
    permissions are entity-wide by design (see StoreRole docstring).
    Otherwise returns the queryset of store ids the user has a StoreRole
    at, which may be empty for a user with no assignment yet.
    """
    if user.is_superuser:
        return None
    if StoreRole.objects.filter(user=user, role=Role.ENTITY_ADMIN).exists():
        return None
    return StoreRole.objects.filter(user=user).values_list('store_id', flat=True)


class TenantScopedQuerySetMixin:
    """Confines a viewset's queryset to the requesting user's entity and,
    for store-tied models, to the stores the user actually holds a role
    at — so a cashier's token can't list or edit another store's (or
    another firm's) data just because the object exists in the database.

    Subclasses set:
      entity_field: ORM lookup from the model to core.Entity's id, e.g.
        'entity_id', 'store__entity_id', 'user__entity_id', or 'pk' when
        the viewset's own model *is* Entity. Required.
      store_fields: ORM lookups from the model to core.Store's id that
        should be OR-ed together, e.g. ('store_id',) or
        ('from_store_id', 'to_store_id'). Leave unset for models that
        aren't tied to one particular store.
    """
    entity_field = None
    store_fields = ()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        if self.entity_field is None:
            return qs
        entity_id = user.entity_id
        if entity_id is None:
            return qs.none()
        qs = qs.filter(**{self.entity_field: entity_id})
        if self.store_fields:
            store_ids = accessible_store_ids(user)
            if store_ids is not None:
                store_ids = list(store_ids)
                store_q = Q()
                for field in self.store_fields:
                    store_q |= Q(**{f'{field}__in': store_ids})
                qs = qs.filter(store_q)
        return qs
