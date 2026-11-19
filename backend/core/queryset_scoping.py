from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from .models import Role, StoreRole
from .request_cache import cached


def store_roles(user):
    """[(role, store_id)] for every StoreRole `user` holds: read once per
    request (core.request_cache), since the permission class, the queryset
    and the serializer of one request all ask."""
    return cached(('store_roles', user.pk), lambda: list(
        StoreRole.objects.filter(user=user).values_list('role', 'store_id')))


def accessible_store_ids(user):
    """Store ids `user` may act on.

    Returns None to mean "every store in the user's entity" — granted to
    Django superusers and to entity_admin StoreRole holders, whose
    permissions are entity-wide by design (see StoreRole docstring).
    Otherwise returns the list of store ids the user has a StoreRole at,
    which may be empty for a user with no assignment yet.

    Every scoped request calls this several times (permission, queryset,
    serializer), so it works from store_roles(): one query per request.
    """
    if user.is_superuser:
        return None
    store_ids = []
    for role, store_id in store_roles(user):
        if role == Role.ENTITY_ADMIN:
            return None
        store_ids.append(store_id)
    return store_ids


def can_access_store(user, store):
    """Whether `user` may act at `store`: it is in their own entity and they
    hold a role there (or are entity-wide). Superusers may act anywhere."""
    if user.is_superuser:
        return True
    if store.entity_id != user.entity_id:
        return False
    store_ids = accessible_store_ids(user)
    return store_ids is None or store.id in store_ids


class TenantScopedQuerySetMixin:
    """Confines a viewset's queryset to the requesting user's entity and,
    for store-tied models, to the stores the user actually holds a role
    at — so a cashier's token can't list or edit another store's (or
    another firm's) data just because the object exists in the database.

    Subclasses set:
      entity_field: ORM lookup from the model to core.Entity's id, e.g.
        'entity_id', 'store__entity_id', 'user__entity_id', or 'pk' when
        the viewset's own model *is* Entity. Required: a viewset that
        forgets it fails loudly rather than serving every firm's rows.
      store_fields: ORM lookups from the model to core.Store's id that
        should be OR-ed together, e.g. ('store_id',) or
        ('from_store_id', 'to_store_id'). Leave unset for models that
        aren't tied to one particular store.
    """
    entity_field = None
    store_fields = ()

    def get_queryset(self):
        if self.entity_field is None:
            raise ImproperlyConfigured(f'{type(self).__name__} must set entity_field to be tenant-scoped.')
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        entity_id = user.entity_id
        if entity_id is None:
            return qs.none()
        qs = qs.filter(**{self.entity_field: entity_id})
        if self.store_fields:
            store_ids = accessible_store_ids(user)
            if store_ids is not None:
                store_q = Q()
                for field in self.store_fields:
                    store_q |= Q(**{f'{field}__in': store_ids})
                qs = qs.filter(store_q)
        return qs
