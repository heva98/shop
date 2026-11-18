import uuid

from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role, StoreRole
from .queryset_scoping import accessible_store_ids


def _has_any_role(user, allowed_roles):
    if user.is_superuser:
        return True
    return StoreRole.objects.filter(user=user, role__in=allowed_roles).exists()


def has_role_at(user, allowed_roles, store_ids):
    """Whether `user` holds one of `allowed_roles` at one of `store_ids`.
    A role held firm-wide (store null) counts everywhere, and anyone who is
    entity_admin is firm-wide for every role they hold, as in
    core.queryset_scoping.accessible_store_ids."""
    if user.is_superuser:
        return True
    rows = list(StoreRole.objects.filter(user=user).values_list('role', 'store_id'))
    if any(role == Role.ENTITY_ADMIN for role, _ in rows):
        return any(role in allowed_roles for role, _ in rows)
    store_ids = {str(s) for s in store_ids}
    return any(role in allowed_roles and (store_id is None or str(store_id) in store_ids) for role, store_id in rows)


def _object_store_ids(obj, view):
    """The stores `obj` belongs to, from the viewset's store_fields
    (core.queryset_scoping), e.g. 'store_id' or 'invoice__store_id'."""
    ids = []
    for field in getattr(view, 'store_fields', ()):
        value = obj
        for part in field.split('__'):
            value = getattr(value, part, None)
            if value is None:
                break
        if value is not None:
            ids.append(value)
    return ids


def _requested_store_ids(request, view):
    """The stores a request names by id: ?store= on a read, or a store
    field (store, from_store, ...) in the body of a write."""
    if request.method in SAFE_METHODS:
        values = [request.query_params.get('store')]
    else:
        data = request.data if hasattr(request.data, 'get') else {}
        names = {f[:-3] for f in getattr(view, 'store_fields', ()) if '__' not in f and f.endswith('_id')} | {'store'}
        values = [data.get(name) for name in names]
    # Anything that isn't a store id is left for the view to refuse with
    # its own message.
    return [v for v in values if isinstance(v, str) and _is_uuid(v)]


def _is_uuid(value):
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


class RoleRequired(BasePermission):
    """Requires the user hold one of `allowed_roles` (core.Role values)
    anywhere in their own entity to access this view at all — read and
    write alike. Use for an endpoint whose tenant-scoped queryset isn't,
    by itself, a tight enough boundary (e.g. customer credit balances,
    which every store role could otherwise *see* via normal scoping but
    shouldn't necessarily be privy to).

    A superuser always passes. Mirrors the frontend's own NAV_DEFS role
    matrix in appData.js, applied to the API that backs each screen, so
    "wrong job" reads as 403, not as an empty list or a scoping-shaped 400.

    The role must be held at the store in question, not just anywhere in
    the firm: the store a request names (?store=, or store/from_store/...
    in a write), and the store of the object acted on. So a storekeeper at
    one branch who is only a cashier at another can't do storekeeper work
    there."""
    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if not _has_any_role(user, self.allowed_roles):
            return False
        # Only stores the user works at: a store they have no role at, or
        # another firm's, is refused by the serializer's own validation
        # (validate_accessible_store) with its message.
        accessible = accessible_store_ids(user)
        store_ids = [s for s in _requested_store_ids(request, view)
                     if accessible is not None and uuid.UUID(s) in accessible]
        return not store_ids or has_role_at(user, self.allowed_roles, store_ids)

    def has_object_permission(self, request, view, obj):
        store_ids = _object_store_ids(obj, view)
        return not store_ids or has_role_at(request.user, self.allowed_roles, store_ids)


class RoleRequiredForWrite(RoleRequired):
    """Same role check, but only for unsafe methods (POST/PUT/PATCH/
    DELETE). Safe methods (GET/HEAD/OPTIONS) just require authentication —
    the real read boundary for most apps is tenant/store scoping
    (core.queryset_scoping), not role, so this is what most viewsets below
    actually use."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return bool(request.user and request.user.is_authenticated)
        return super().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return super().has_object_permission(request, view, obj)


def roles(*allowed_roles):
    """`permission_classes = [roles(Role.CASHIER, Role.STOREKEEPER)]` —
    a one-off RoleRequired subclass without a module-level class per call site."""
    return type('_RoleGate', (RoleRequired,), {'allowed_roles': allowed_roles})


def write_roles(*allowed_roles):
    """Same, but gating writes only — see RoleRequiredForWrite."""
    return type('_WriteRoleGate', (RoleRequiredForWrite,), {'allowed_roles': allowed_roles})


def is_store_manager(user, store):
    """Who may approve a void, a stock count or a write-off, or close
    someone else's shift: the store's own manager, or an entity_admin of
    the same firm."""
    if user is None or not user.is_active:
        return False
    if user.is_superuser:
        return True
    return StoreRole.objects.filter(
        Q(store=store, role=Role.STORE_MANAGER)
        | Q(store__isnull=True, role=Role.ENTITY_ADMIN, user__entity_id=store.entity_id),
        user=user,
    ).exists()


class SuperuserForWrite(BasePermission):
    """Reads need only a signed-in user; writes need a superuser. For
    platform-wide rows every firm shares (core.ModuleRegistry), which no
    single firm's admin may change for the others."""

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or user.is_superuser
