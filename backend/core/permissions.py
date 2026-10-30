from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Role, StoreRole


def _has_any_role(user, allowed_roles):
    if user.is_superuser:
        return True
    return StoreRole.objects.filter(user=user, role__in=allowed_roles).exists()


class RoleRequired(BasePermission):
    """Requires the user hold one of `allowed_roles` (core.Role values)
    anywhere in their own entity to access this view at all — read and
    write alike. Use for an endpoint whose tenant-scoped queryset isn't,
    by itself, a tight enough boundary (e.g. customer credit balances,
    which every store role could otherwise *see* via normal scoping but
    shouldn't necessarily be privy to).

    A superuser always passes. Mirrors the frontend's own NAV_DEFS role
    matrix in appData.js, applied to the API that backs each screen, so
    "wrong job" reads as 403, not as an empty list or a scoping-shaped 400."""
    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        return _has_any_role(user, self.allowed_roles)


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
