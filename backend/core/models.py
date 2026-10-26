import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class Entity(models.Model):
    """The owning organization. main_store nullable = peer mode (each store
    independent); set = hub mode (main_store fulfils other stores' enquiries).

    store_mode = single: the firm trades from exactly one store, which
    ensure_single_store() creates so staff, sales and stock always have a
    store to belong to. The UI then hides stores altogether; switching to
    multi later just allows more of them — nothing has to be migrated.
    """
    class PriceMode(models.TextChoices):
        ENTITY = 'entity', 'Shared price list for all stores'
        STORE = 'store', 'Each store sets its own prices'

    class StoreMode(models.TextChoices):
        SINGLE = 'single', 'Single shop'
        MULTI = 'multi', 'Shop with multiple branches'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    tin = models.CharField('TIN', max_length=32, blank=True)
    logo = models.ImageField(
        upload_to='entity_logos/', null=True, blank=True,
        help_text='Shown in the app header and on printed documents for this firm.',
    )
    main_store = models.ForeignKey(
        'core.Store', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', help_text='Nullable = peer mode. Set = hub mode.',
    )
    price_mode = models.CharField(
        max_length=10, choices=PriceMode.choices, default=PriceMode.ENTITY,
        help_text='Set at onboarding: whether pricing.Price is one shared list for the '
                   'entity or set independently per store. See pricing.Price.get_price.',
    )
    store_mode = models.CharField(
        max_length=10, choices=StoreMode.choices, default=StoreMode.MULTI,
        help_text='Single = one store, created automatically and hidden in the app. '
                  'Multi = the admin adds and manages stores.',
    )
    cashier_discount_limit = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        help_text='The largest discount, as a percent of the sale, a cashier may give without a manager. '
                  'Managers may give any discount.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_single_store(self):
        return self.store_mode == self.StoreMode.SINGLE

    def ensure_single_store(self):
        """The one store of a single-store firm, created (named after the
        firm) if it has none yet. Returns None for a multi-store firm."""
        if not self.is_single_store:
            return None
        store = self.stores.filter(is_active=True).order_by('created_at').first()
        if store is None:
            store = Store.objects.create(entity=self, name=self.name)
        return store


class Store(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=255)
    tin = models.CharField('TIN', max_length=32, blank=True)
    address = models.CharField(max_length=255, blank=True)
    efd_device_id = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_main(self):
        return self.entity.main_store_id == self.id

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    CASHIER = 'cashier', 'Cashier'
    STOREKEEPER = 'storekeeper', 'Storekeeper'
    STORE_MANAGER = 'store_manager', 'Store manager'
    ENTITY_ADMIN = 'entity_admin', 'Entity admin'


class User(AbstractUser):
    class Gender(models.TextChoices):
        MALE = 'male', 'Male'
        FEMALE = 'female', 'Female'

    class Qualification(models.TextChoices):
        PRIMARY = 'primary', 'Primary education'
        O_LEVEL = 'o_level', 'Secondary (O-level)'
        A_LEVEL = 'a_level', 'Advanced secondary (A-level)'
        CERTIFICATE = 'certificate', 'Certificate'
        DIPLOMA = 'diploma', 'Diploma'
        BACHELOR = 'bachelor', "Bachelor's degree"
        MASTER = 'master', "Master's degree"
        DOCTORATE = 'doctorate', 'Doctorate (PhD)'

    entity = models.ForeignKey(Entity, null=True, blank=True, on_delete=models.SET_NULL, related_name='users')
    # Blank-able at the model level so createsuperuser and existing rows keep
    # working; UserSerializer requires them when an admin creates staff.
    middle_name = models.CharField(max_length=150, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    highest_qualification = models.CharField(max_length=20, choices=Qualification.choices, blank=True)
    phone = models.CharField(
        max_length=20, blank=True,
        help_text='Mobile number for SMS summaries, in international form, e.g. 255712345678.',
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text='Set when an admin chooses the password; the user must pick their own at next sign-in.',
    )

    class Meta:
        ordering = ['username']


class StoreRole(models.Model):
    """A user's role, scoped to one store — except entity_admin rows, whose
    permissions are evaluated entity-wide and leave store null."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='store_roles')
    store = models.ForeignKey(Store, null=True, blank=True, on_delete=models.CASCADE, related_name='user_roles')
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        unique_together = [('user', 'store', 'role')]

    def __str__(self):
        return f'{self.user} @ {self.store or "entity"} ({self.role})'


class ModuleRegistry(models.Model):
    """Declares an installed pluggable module and its scope. Backs the
    Settings > Module registry screen; drives both API permission checks
    and (already, on the frontend) menu rendering."""
    class Scope(models.TextChoices):
        ENTITY = 'entity', 'Entity'
        STORE = 'store', 'Store'

    key = models.SlugField(max_length=64, unique=True, help_text='e.g. "pos", "customer_credit"')
    name = models.CharField(max_length=128)
    scope = models.CharField(max_length=10, choices=Scope.choices)
    implements = models.CharField(
        max_length=64, blank=True,
        help_text='Pluggable interface fulfilled, if any: FiscalDevice, PaymentMethod, NotificationChannel, FulfillmentStrategy',
    )

    def __str__(self):
        return self.name


class ModuleEnablement(models.Model):
    """Per-entity (store null) or per-store on/off flag for a module."""
    module = models.ForeignKey(ModuleRegistry, on_delete=models.CASCADE, related_name='enablements')
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='module_enablements')
    store = models.ForeignKey(
        Store, null=True, blank=True, on_delete=models.CASCADE, related_name='module_enablements',
        help_text='Null for entity-scoped modules',
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [('module', 'entity', 'store')]

    def __str__(self):
        return f'{self.module} @ {self.store or self.entity} = {self.enabled}'
