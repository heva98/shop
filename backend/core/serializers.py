import re
from datetime import date

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Entity, ModuleEnablement, ModuleRegistry, Role, Store, StoreRole, User
from .queryset_scoping import accessible_store_ids


class ClientGeneratedIdMixin(serializers.Serializer):
    """Lets an offline-first client submit its own pre-generated UUID
    primary key on create. architecture.txt §3/§4: every syncable record's
    id is client-generated so a store's till and the cloud never collide
    on the same id when merging — a till that's been offline for part of
    a day still needs its own Sale/StockBatch/etc. id to be final the
    moment it's created locally, not assigned later by the server.

    Every model this applies to already has id = UUIDField(default=uuid4,
    editable=False); editable=False is what makes DRF's ModelSerializer
    mark the auto-generated field read-only, so it must be redeclared
    explicitly here rather than just listed in Meta.fields. required=False
    keeps every existing caller that omits id working unchanged, falling
    back to the model's own default."""
    id = serializers.UUIDField(required=False)


def validate_owned_entity(entity, request):
    """For a serializer's validate_entity: reject an `entity` FK value
    that isn't the requesting user's own (superusers exempt). Read-side
    get_queryset() filtering can't stop a client writing a foreign id
    into the request body, so every writable entity/store FK needs this
    checked explicitly on create/update."""
    if entity is not None and request is not None and not request.user.is_superuser:
        if entity.id != request.user.entity_id:
            raise serializers.ValidationError('Must be your own entity.')
    return entity


def validate_owned_store(store, request):
    """Same idea for a `store` FK: its entity must be the requesting
    user's own entity (superusers exempt)."""
    if store is not None and request is not None and not request.user.is_superuser:
        if store.entity_id != request.user.entity_id:
            raise serializers.ValidationError('Must be a store in your own entity.')
    return store


def validate_owned(obj, request, message='Must belong to your own shop.'):
    """Same idea for any other FK to entity-owned data (a Product, a
    UnitOfMeasure, ...): `obj.entity_id` must be the requesting user's own
    entity (superusers exempt)."""
    if obj is not None and request is not None and not request.user.is_superuser:
        if obj.entity_id != request.user.entity_id:
            raise serializers.ValidationError(message)
    return obj


def validate_accessible_store(store, request):
    """Stricter than validate_owned_store: for a field naming the store an
    object *belongs to* or the store the user is *acting from* (a Sale's
    store, a StockBatch's store, ...), same-entity isn't enough — a
    cashier assigned to Store A could otherwise write records for Store B
    just because both happen to be in the same firm. Requires an actual
    StoreRole at that store (entity_admin/superuser are entity-wide and
    exempt, matching accessible_store_ids)."""
    store = validate_owned_store(store, request)
    if store is None or request is None or request.user.is_superuser:
        return store
    store_ids = accessible_store_ids(request.user)
    if store_ids is not None and store.id not in list(store_ids):
        raise serializers.ValidationError('You do not have access to this store.')
    return store


class StoreSerializer(serializers.ModelSerializer):
    is_main = serializers.BooleanField(read_only=True)

    class Meta:
        model = Store
        fields = [
            'id', 'entity', 'name', 'tin', 'address',
            'efd_device_id', 'is_active', 'is_main', 'created_at',
        ]
        # Defaults to the caller's own entity in StoreViewSet.perform_create.
        extra_kwargs = {'entity': {'required': False}}

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))


_MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB — plenty for a header/print logo


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = ['id', 'name', 'tin', 'business_type', 'phone', 'email', 'region', 'district', 'address',
                  'is_active', 'logo', 'main_store', 'price_mode', 'store_mode', 'cashier_discount_limit', 'created_at']
        # Suspending a shop is the platform administrator's (core.platform).
        read_only_fields = ['is_active']

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_store_mode(self, mode):
        entity = self.instance
        if (mode == Entity.StoreMode.SINGLE and entity is not None
                and entity.stores.filter(is_active=True).count() > 1):
            raise serializers.ValidationError(
                'This shop has more than one active store. Deactivate or remove the others first.')
        return mode

    def save(self, **kwargs):
        entity = super().save(**kwargs)
        entity.ensure_single_store()
        return entity

    def validate_logo(self, logo):
        if logo is not None and hasattr(logo, 'size') and logo.size > _MAX_LOGO_SIZE:
            raise serializers.ValidationError('Logo must be 2MB or smaller.')
        return logo

    def validate_main_store(self, store):
        entity = self.instance
        if store is not None and entity is not None and store.entity_id != entity.id:
            raise serializers.ValidationError('main_store must belong to this entity.')
        return store


def normalize_phone(value):
    """Accepts what people type — 0712 345 678, +255 712 345 678,
    255712345678 — and stores 255712345678, the form SMS gateways need."""
    digits = re.sub(r'[\s\-()+]', '', value or '')
    if not digits:
        return ''
    if not digits.isdigit():
        raise serializers.ValidationError('Use digits only, e.g. 0712 345 678.')
    if len(digits) == 10 and digits.startswith('0'):
        digits = '255' + digits[1:]
    if not 10 <= len(digits) <= 15:
        raise serializers.ValidationError('Enter a full mobile number, e.g. 0712 345 678.')
    return digits


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'id', 'username', 'password', 'first_name', 'middle_name', 'last_name',
            'gender', 'date_of_birth', 'highest_qualification', 'email', 'phone', 'entity', 'is_active',
            'must_change_password',
        ]
        read_only_fields = ['must_change_password']

    # Required when an admin creates a user; optional on PATCH (partial=True
    # skips required checks) so existing users can be edited piecemeal.
    _REQUIRED_ON_CREATE = ('password', 'first_name', 'last_name', 'gender', 'date_of_birth', 'highest_qualification')

    def validate_entity(self, entity):
        request = self.context.get('request')
        if entity is None and request is not None and not request.user.is_superuser:
            # Unlinking staff from the shop would leave them in no shop at all.
            raise serializers.ValidationError('Must be your own entity.')
        return validate_owned_entity(entity, request)

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_date_of_birth(self, dob):
        if dob is not None and dob >= date.today():
            raise serializers.ValidationError('Date of birth must be in the past.')
        return dob

    def validate(self, attrs):
        request = self.context.get('request')
        if (self.instance is not None and request is not None
                and self.instance.pk == request.user.pk and attrs.get('is_active') is False):
            raise serializers.ValidationError({'is_active': 'You cannot disable your own account.'})
        if self.instance is None:
            missing = {f: 'This field is required.' for f in self._REQUIRED_ON_CREATE if not attrs.get(f)}
            if missing:
                raise serializers.ValidationError(missing)
        password = attrs.get('password')
        if password:
            candidate = self.instance or User(**{k: v for k, v in attrs.items() if k != 'password'})
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop('password')
        request = self.context.get('request')
        # New staff default to the creating admin's own entity.
        if 'entity' not in validated_data and request is not None:
            validated_data['entity'] = request.user.entity
        user = User(**validated_data)
        user.set_password(password)
        # The admin chose this password, so it isn't secret from them: the
        # new staff member sets their own at first sign-in.
        user.must_change_password = True
        user.save()
        return user

    def update(self, instance, validated_data):
        from .authentication import revoke_sessions

        password = validated_data.pop('password', None)
        was_active = instance.is_active
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.must_change_password = True
            user.save(update_fields=['password', 'must_change_password'])
        if password or (was_active and not user.is_active):
            revoke_sessions(user)
        return user


class OwnProfileSerializer(serializers.ModelSerializer):
    """What any signed-in user may change about themselves via
    /users/me/. Username, entity and is_active stay admin-controlled
    (UserSerializer); a password change must prove the current one."""
    current_password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = [
            'first_name', 'middle_name', 'last_name', 'gender', 'date_of_birth',
            'highest_qualification', 'email', 'phone', 'current_password', 'new_password',
        ]

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate_date_of_birth(self, dob):
        if dob is not None and dob >= date.today():
            raise serializers.ValidationError('Date of birth must be in the past.')
        return dob

    def validate(self, attrs):
        new_password = attrs.get('new_password')
        if new_password:
            if not self.instance.check_password(attrs.get('current_password') or ''):
                raise serializers.ValidationError({'current_password': 'Current password is incorrect.'})
            try:
                validate_password(new_password, user=self.instance)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'new_password': list(exc.messages)})
        return attrs

    def update(self, instance, validated_data):
        validated_data.pop('current_password', None)
        new_password = validated_data.pop('new_password', None)
        user = super().update(instance, validated_data)
        if new_password:
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password'])
        return user


_OWNER_ROLE_MESSAGE = 'Only the platform administrator can make someone a shop owner.'


class StoreRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreRole
        fields = ['id', 'user', 'store', 'role']

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def validate(self, attrs):
        request = self.context.get('request')
        target_user = attrs.get('user', getattr(self.instance, 'user', None))
        if request and not request.user.is_superuser:
            if target_user is not None and target_user.entity_id != request.user.entity_id:
                raise serializers.ValidationError({'user': 'Must be a user in your own entity.'})
            if Role.ENTITY_ADMIN in (attrs.get('role'), getattr(self.instance, 'role', None)):
                raise serializers.ValidationError({'role': _OWNER_ROLE_MESSAGE})
        # A single-store firm's staff all work at its one store, so the
        # client needn't (and in the UI can't) pick it.
        role = attrs.get('role', getattr(self.instance, 'role', None))
        store = attrs['store'] if 'store' in attrs else getattr(self.instance, 'store', None)
        entity = getattr(target_user, 'entity', None)
        if (role != Role.ENTITY_ADMIN and store is None
                and entity is not None and entity.is_single_store):
            attrs['store'] = entity.ensure_single_store()
        return attrs


class ModuleRegistrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ModuleRegistry
        fields = ['id', 'key', 'name', 'scope', 'implements']


class ModuleEnablementSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModuleEnablement
        fields = ['id', 'module', 'entity', 'store', 'enabled']

    def validate_entity(self, entity):
        return validate_owned_entity(entity, self.context.get('request'))

    def validate_store(self, store):
        return validate_accessible_store(store, self.context.get('request'))

    def validate(self, attrs):
        entity = attrs.get('entity', getattr(self.instance, 'entity', None))
        store = attrs.get('store', getattr(self.instance, 'store', None))
        if entity is not None and store is not None and store.entity_id != entity.id:
            raise serializers.ValidationError({'store': "Store must belong to the enablement's entity."})
        return attrs
