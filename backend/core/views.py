from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from audit.services import Action, record

from .features import FEATURES, FEATURES_BY_KEY, feature_values, is_enabled, set_feature, unavailable_reason
from .models import Entity, ModuleEnablement, ModuleRegistry, Role, Store, StoreRole, User
from .permissions import SuperuserForWrite, roles, write_roles
from .queryset_scoping import TenantScopedQuerySetMixin
from .serializers import (
    EntitySerializer,
    ModuleEnablementSerializer,
    ModuleRegistrySerializer,
    OwnProfileSerializer,
    StoreRoleSerializer,
    StoreSerializer,
    UserSerializer,
)

_ADMIN_WRITE_ROLES = (Role.ENTITY_ADMIN,)
_SINGLE_STORE_MESSAGE = (
    'Your shop is set up as a single shop. To add another store, switch to '
    '"Shop with multiple branches" under Admin > Shop profile.'
)


class EntityViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    """Onboarding a new firm (creating an Entity — the tenant root itself)
    is a platform-admin action, not something any authenticated user's
    token should be able to do; everything else (view/edit your own
    entity) still goes through the normal entity-scoped queryset. Editing
    (price_mode, main_store/topology) is entity_admin territory — Network
    topology in Settings, NAV_DEFS in appData.js — same as the rest of
    Admin/Settings, layered under the stricter superuser-only create check
    below."""
    queryset = Entity.objects.all()
    serializer_class = EntitySerializer
    entity_field = 'pk'
    permission_classes = [write_roles(*_ADMIN_WRITE_ROLES)]

    def perform_create(self, serializer):
        if not self.request.user.is_superuser:
            raise PermissionDenied('Only a superuser can create a new entity.')
        serializer.save()

    def perform_update(self, serializer):
        before = {f: getattr(serializer.instance, f) for f in ('name', 'tin', 'price_mode', 'store_mode', 'main_store_id')}
        entity = serializer.save()
        changed = {f: [str(v), str(getattr(entity, f))] for f, v in before.items() if getattr(entity, f) != v}
        if changed:
            record(Action.SETTINGS_CHANGED, f'Shop profile changed: {", ".join(changed)}',
                   request=self.request, entity=entity, data=changed)


class StoreViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = Store.objects.select_related('entity').all()
    serializer_class = StoreSerializer
    filterset_fields = ['entity', 'is_active']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_ADMIN_WRITE_ROLES)]

    def perform_create(self, serializer):
        """A store goes under the caller's own entity unless the body names
        one (validate_entity already refuses a foreign one for non-superusers)."""
        entity = serializer.validated_data.get('entity') or self.request.user.entity
        if entity is None:
            raise ValidationError({'entity': 'Your account is not linked to a shop.'})
        if entity.is_single_store and entity.stores.filter(is_active=True).exists():
            raise ValidationError({'detail': _SINGLE_STORE_MESSAGE})
        serializer.save(entity=entity)

    def perform_update(self, serializer):
        store = serializer.instance
        activating = serializer.validated_data.get('is_active')
        if store.entity.is_single_store and activating is not None and activating != store.is_active:
            if activating and store.entity.stores.filter(is_active=True).exists():
                raise ValidationError({'detail': _SINGLE_STORE_MESSAGE})
            if not activating:
                raise ValidationError({'detail': 'This is your shop\'s only store, so it cannot be deactivated.'})
        serializer.save()

    def perform_destroy(self, instance):
        """Removing a store is only for one with no trading history — sales,
        stock ledger, transfers and the controlled-substances register all
        PROTECT their store, since those are records that must outlive it.
        Such a store gets deactivated (is_active=False) instead. The main
        store is refused too: deleting it would silently drop the entity
        from hub to peer mode, which belongs in Settings > Network topology."""
        if instance.entity.is_single_store and instance.is_active:
            raise ValidationError({'detail': 'This is your shop\'s only store, so it cannot be removed.'})
        if instance.is_main:
            raise ValidationError({'detail': (
                'This is the main store. Switch the network topology to peer mode '
                'or choose another main store before removing it.'
            )})
        try:
            with transaction.atomic():
                instance.delete()
        except ProtectedError:
            raise ValidationError({'detail': (
                f'"{instance.name}" has sales, stock movements, transfers or controlled-substance '
                'records, so it cannot be removed. Deactivate it instead.'
            )})


class UserViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_ADMIN_WRITE_ROLES)]

    def _refuse_other_owner(self, target):
        """A shop owner manages their staff, not their fellow owners: only
        the platform administrator edits, resets or removes an owner's
        account (an owner edits their own through users/me/)."""
        user = self.request.user
        if (not user.is_superuser and target.pk != user.pk
                and target.store_roles.filter(role=Role.ENTITY_ADMIN).exists()):
            raise PermissionDenied("Only the platform administrator can change another shop owner's account.")

    def perform_create(self, serializer):
        user = serializer.save()
        record(Action.USER_CREATED, f'User {user.username} created', request=self.request, data={'user': user.username})

    def perform_update(self, serializer):
        self._refuse_other_owner(serializer.instance)
        was_active = serializer.instance.is_active
        resetting = bool(serializer.validated_data.get('password'))
        # The admin form sends every field; log only the ones that changed.
        before = {f: getattr(serializer.instance, f) for f in serializer.validated_data if f != 'password'}
        user = serializer.save()
        target = {'user': user.username}
        if was_active and not user.is_active:
            record(Action.USER_DISABLED, f'User {user.username} disabled', request=self.request, data=target)
        elif not was_active and user.is_active:
            record(Action.USER_ENABLED, f'User {user.username} enabled', request=self.request, data=target)
        if resetting:
            record(Action.PASSWORD_RESET, f'Password of {user.username} reset', request=self.request, data=target)
        changed = sorted(f for f, old in before.items() if f != 'is_active' and getattr(user, f) != old)
        if changed:
            record(Action.USER_UPDATED, f'User {user.username} changed: {", ".join(changed)}',
                   request=self.request, data=target)

    def perform_destroy(self, instance):
        self._refuse_other_owner(instance)
        instance.delete()

    @action(detail=False, methods=['get', 'patch'], permission_classes=[IsAuthenticated])
    def me(self, request):
        """GET: the one payload the frontend needs right after login: who
        the user is, what entity/topology they're in, and which store(s)
        they hold a role at — StoreRole.store is null for an entity_admin
        row, whose permissions are entity-wide (see StoreRole's docstring).

        PATCH: any signed-in user (not just entity_admin) edits their own
        profile through OwnProfileSerializer; returns the same payload."""
        user = request.user
        if request.method == 'PATCH':
            serializer = OwnProfileSerializer(user, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
            if serializer.validated_data.get('new_password'):
                record(Action.PASSWORD_CHANGED, f'{user.username} changed their password', request=request)
        store_roles = StoreRole.objects.filter(user=user).select_related('store')
        entity = user.entity if user.entity_id else None
        return Response({
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'middle_name': user.middle_name,
            'last_name': user.last_name,
            'gender': user.gender,
            'date_of_birth': user.date_of_birth,
            'email': user.email,
            'phone': user.phone,
            'must_change_password': user.must_change_password,
            'is_superuser': user.is_superuser,
            'entity': EntitySerializer(entity).data if entity else None,
            'store_roles': [
                {
                    'id': sr.id,
                    'store': sr.store_id,
                    'store_name': sr.store.name if sr.store_id else None,
                    'role': sr.role,
                    'features': feature_values(entity, sr.store),
                }
                for sr in store_roles
            ],
        })


@api_view(['GET', 'PATCH'])
@permission_classes([roles(Role.ENTITY_ADMIN)])
def features(request):
    """Settings > Features. GET: every feature with its value for the firm
    and for each store. PATCH {key, store (null for the whole firm),
    enabled} switches one."""
    entity = request.user.entity
    if entity is None:
        raise ValidationError('Your account is not linked to a shop.')
    if request.method == 'PATCH':
        key = request.data.get('key')
        if key not in FEATURES_BY_KEY:
            raise ValidationError({'key': 'Unknown feature.'})
        feature = FEATURES_BY_KEY[key]
        store = None
        if request.data.get('store'):
            store = Store.objects.filter(entity=entity, pk=request.data['store']).first()
            if store is None:
                raise ValidationError({'store': 'Not a store in your shop.'})
        enabled = str(request.data.get('enabled')).lower() in ('true', '1', 'yes')
        reason = unavailable_reason(key, entity)
        if enabled and reason:
            raise ValidationError({'detail': f'{feature.label}: {reason}'})
        set_feature(key, enabled, entity=entity, store=store)
        where = f' at {store.name}' if store is not None and feature.scope == ModuleRegistry.Scope.STORE else ''
        record(Action.SETTINGS_CHANGED, f'{feature.label} switched {"on" if enabled else "off"}{where}',
               request=request, entity=entity, store=store, data={'feature': key, 'enabled': enabled})
    stores = list(entity.stores.order_by('name'))
    return Response({
        'features': [
            {
                'key': f.key, 'label': f.label, 'description': f.description, 'scope': f.scope,
                'unavailable': unavailable_reason(f.key, entity),
                'firm': is_enabled(f.key, entity=entity),
                'stores': {str(s.id): is_enabled(f.key, store=s) for s in stores}
                if f.scope == ModuleRegistry.Scope.STORE else {},
            }
            for f in FEATURES
        ],
        'stores': [{'id': str(s.id), 'name': s.name, 'is_active': s.is_active} for s in stores],
    })


class StoreRoleViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = StoreRole.objects.select_related('user', 'store').all()
    serializer_class = StoreRoleSerializer
    filterset_fields = ['store', 'role', 'user']
    entity_field = 'user__entity_id'
    permission_classes = [write_roles(*_ADMIN_WRITE_ROLES)]

    def _describe(self, role):
        return f'{role.get_role_display()} at {role.store.name if role.store_id else "all stores"} for {role.user.username}'

    def perform_create(self, serializer):
        role = serializer.save()
        record(Action.ROLE_GRANTED, self._describe(role), request=self.request, store=role.store)

    def perform_destroy(self, instance):
        if instance.role == Role.ENTITY_ADMIN and not self.request.user.is_superuser:
            raise PermissionDenied('Only the platform administrator can remove a shop owner.')
        summary, store = self._describe(instance), instance.store
        instance.delete()
        record(Action.ROLE_REMOVED, summary, request=self.request, store=store)


class ModuleRegistryViewSet(viewsets.ModelViewSet):
    """Global catalog of installable module definitions (not tenant data —
    same rows for every entity), so it is intentionally left unscoped —
    and for the same reason only a superuser may change it: deleting a
    row would wipe every firm's switches for that module."""
    queryset = ModuleRegistry.objects.order_by('name')
    serializer_class = ModuleRegistrySerializer
    permission_classes = [SuperuserForWrite]


class ModuleEnablementViewSet(TenantScopedQuerySetMixin, viewsets.ModelViewSet):
    queryset = ModuleEnablement.objects.select_related('module', 'entity', 'store').all()
    serializer_class = ModuleEnablementSerializer
    filterset_fields = ['entity', 'store', 'module']
    entity_field = 'entity_id'
    permission_classes = [write_roles(*_ADMIN_WRITE_ROLES)]
