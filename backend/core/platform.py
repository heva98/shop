"""/api/platform/: the platform administrator's console — the superuser who
runs this server for many shops. Registering a shop creates its Entity,
its first Store and its owner (an entity_admin) in one step; from there
the owner adds their own sellers under Admin > Users. Suspending a shop
signs its staff out and keeps them out (core.authentication).

Nothing here is reachable by a shop's own staff, owners included."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from audit.services import Action, record

from .authentication import revoke_sessions
from .models import Entity, Role, Store, StoreRole, User
from .serializers import normalize_phone


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class OwnerSerializer(serializers.ModelSerializer):
    """A shop owner as the platform console shows and creates them. The
    password is the platform administrator's choice, so the owner must
    pick their own at first sign-in (must_change_password)."""
    password = serializers.CharField(write_only=True, style={'input_type': 'password'}, trim_whitespace=False)

    class Meta:
        model = User
        fields = ['id', 'username', 'password', 'first_name', 'last_name', 'phone', 'email', 'is_active',
                  'last_login']
        read_only_fields = ['is_active', 'last_login']
        extra_kwargs = {'first_name': {'required': True, 'allow_blank': False},
                        'last_name': {'required': True, 'allow_blank': False}}

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('That username is taken.')
        return value

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate(self, attrs):
        try:
            validate_password(attrs['password'], user=User(**{k: v for k, v in attrs.items() if k != 'password'}))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        entity = self.context['entity']
        password = validated_data.pop('password')
        user = User(entity=entity, must_change_password=True, **validated_data)
        user.set_password(password)
        user.save()
        StoreRole.objects.create(user=user, store=None, role=Role.ENTITY_ADMIN)
        return user


class ShopSerializer(serializers.ModelSerializer):
    """A shop for the platform console. On create, `owner` is required and
    becomes the shop's first owner; afterwards owners are added with
    POST <id>/owners/."""
    owner = OwnerSerializer(write_only=True, required=False)
    owners = serializers.SerializerMethodField()
    business_type_label = serializers.CharField(source='get_business_type_display', read_only=True)
    store_count = serializers.IntegerField(read_only=True)
    staff_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Entity
        fields = ['id', 'name', 'tin', 'business_type', 'business_type_label', 'phone', 'email', 'region',
                  'district', 'address', 'store_mode', 'price_mode', 'is_active', 'created_at',
                  'owner', 'owners', 'store_count', 'staff_count']
        read_only_fields = ['created_at']

    def get_owners(self, entity):
        owners = getattr(entity, 'owners', None)  # prefetched by ShopViewSet
        if owners is None:
            owners = entity.users.filter(store_roles__role=Role.ENTITY_ADMIN).distinct()
        return OwnerSerializer(owners, many=True).data

    def validate_phone(self, value):
        return normalize_phone(value)

    def validate(self, attrs):
        if self.instance is None and 'owner' not in attrs:
            raise serializers.ValidationError({'owner': 'A new shop needs its owner.'})
        if self.instance is not None and 'owner' in attrs:
            raise serializers.ValidationError({'owner': 'Add owners to an existing shop with its owners action.'})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        owner_data = validated_data.pop('owner')
        entity = Entity.objects.create(**validated_data)
        # A single shop's one store is the shop; a multi-branch firm starts
        # with its first branch at the shop's own address.
        store = entity.ensure_single_store() or Store.objects.create(entity=entity, name=entity.name)
        if entity.address and not store.address:
            store.address = entity.address
            store.save(update_fields=['address'])
        OwnerSerializer(context={'entity': entity}).create(owner_data)
        return entity


class ShopViewSet(viewsets.ModelViewSet):
    """GET/POST /api/platform/shops/, GET/PATCH /api/platform/shops/<id>/.
    POST <id>/owners/ adds another owner. PATCH {is_active: false}
    suspends the shop. Shops are never deleted here: their sales and stock
    history must outlive them; suspend instead."""
    serializer_class = ShopSerializer
    permission_classes = [IsPlatformAdmin]
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    search_fields = ['name', 'region', 'district', 'phone']
    filterset_fields = ['business_type', 'is_active']

    def get_queryset(self):
        owners = User.objects.filter(store_roles__role=Role.ENTITY_ADMIN).distinct().order_by('first_name')
        return (Entity.objects
                .annotate(store_count=Count('stores', filter=Q(stores__is_active=True), distinct=True),
                          staff_count=Count('users', filter=Q(users__is_active=True), distinct=True))
                .prefetch_related(Prefetch('users', queryset=owners, to_attr='owners'))
                .order_by('name'))

    def perform_create(self, serializer):
        entity = serializer.save()
        record(Action.SHOP_REGISTERED, f'Shop {entity.name} registered', request=self.request, entity=entity,
               data={'owner': [o.username for o in entity.users.all()]})

    def perform_update(self, serializer):
        was_active = serializer.instance.is_active
        entity = serializer.save()
        if was_active and not entity.is_active:
            for user in entity.users.all():
                revoke_sessions(user)
            record(Action.SHOP_SUSPENDED, f'Shop {entity.name} suspended', request=self.request, entity=entity)
        elif not was_active and entity.is_active:
            record(Action.SHOP_REACTIVATED, f'Shop {entity.name} reactivated', request=self.request, entity=entity)

    @action(detail=True, methods=['post'])
    def owners(self, request, pk=None):
        entity = self.get_object()
        serializer = OwnerSerializer(data=request.data, context={'entity': entity})
        serializer.is_valid(raise_exception=True)
        owner = serializer.save()
        record(Action.USER_CREATED, f'Owner {owner.username} added to {entity.name}', request=request,
               entity=entity, data={'user': owner.username})
        return Response(OwnerSerializer(owner).data, status=201)
