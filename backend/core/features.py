"""Features a firm can switch on or off, for the whole firm or per store.

Backed by core.ModuleEnablement (one row per module and entity, plus one
per store for store-level features). A store row overrides the firm row;
with no row at all the feature's default applies, so a firm onboarded
before a feature existed keeps working the way it always has.

`require()` is what the API calls before doing something a switched-off
feature would allow; the frontend hides the matching screens using the
same values (`/api/core/users/me/` returns them).

A feature marked multi_store_only is always off for a single-store firm
(Entity.store_mode), whatever its switch says, and its switch can't be
turned on there. The stored switch is left alone, so a firm that moves to
multiple stores gets back whatever it had chosen.
"""

from dataclasses import dataclass

from django.utils.translation import gettext, gettext_lazy
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import Entity, ModuleEnablement, ModuleRegistry


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    scope: str  # ModuleRegistry.Scope value
    default: bool
    description: str
    multi_store_only: bool = False
    pharmacy_only: bool = False


FEATURES = [
    Feature('pos_sale', gettext_lazy('Point of sale'), ModuleRegistry.Scope.STORE, True,
            gettext_lazy('Selling to customers at the till. Switch off for a store that only holds stock, such as a warehouse.')),
    Feature('receiving_invoice', gettext_lazy('Receiving from suppliers'), ModuleRegistry.Scope.STORE, True,
            gettext_lazy('Entering supplier invoices. Switch off for a branch that only gets stock from the main store.')),
    Feature('customer_credit', gettext_lazy('Sales on credit'), ModuleRegistry.Scope.STORE, True,
            gettext_lazy("Putting sales on a registered customer's account (madeni) and taking their repayments. Set each customer's credit limit under Customers.")),
    Feature('controlled_substances_register', gettext_lazy('Controlled drugs register'), ModuleRegistry.Scope.STORE, True,
            gettext_lazy('Selling controlled drugs, each recorded in the register with the patient, prescriber '
                         'and who sold it. Switch off for a branch that does not stock them.'),
            pharmacy_only=True),
    Feature('transfer', gettext_lazy('Transfers between stores'), ModuleRegistry.Scope.ENTITY, True,
            gettext_lazy('Branches asking each other for stock, and sending stock between them.'),
            multi_store_only=True),
    Feature('analytics_dashboards', gettext_lazy('Analytics'), ModuleRegistry.Scope.ENTITY, True,
            gettext_lazy('The Analytics screen: the data visualizer, saved visualizations and dashboard pins.')),
]
FEATURES_BY_KEY = {f.key: f for f in FEATURES}

SINGLE_STORE_REASON = gettext_lazy('Not available for a single shop. Switch to multiple stores under Admin > Shop profile.')
PHARMACY_REASON = gettext_lazy('Only for pharmacies. Change the type of business under Admin > Shop profile.')


def unavailable_reason(key, entity):
    """Why `key` can't be on for `entity` (an Entity), or None if it can."""
    feature = FEATURES_BY_KEY[key]
    if feature.multi_store_only and entity is not None and entity.is_single_store:
        return SINGLE_STORE_REASON
    if feature.pharmacy_only and entity is not None and not entity.is_pharmacy:
        return PHARMACY_REASON
    return None


def _blocked_reason(feature, entity_id):
    """unavailable_reason() from an entity id, looking the firm up only
    for a feature that depends on it."""
    if not (feature.multi_store_only or feature.pharmacy_only):
        return None
    return unavailable_reason(feature.key, Entity.objects.filter(pk=entity_id).first())


def is_enabled(key, *, entity=None, store=None):
    feature = FEATURES_BY_KEY[key]
    entity_id = store.entity_id if store is not None else getattr(entity, 'id', entity)
    if _blocked_reason(feature, entity_id):
        return False
    rows = {row.store_id: row.enabled for row in ModuleEnablement.objects.filter(module__key=key, entity_id=entity_id)}
    if store is not None and feature.scope == ModuleRegistry.Scope.STORE and store.id in rows:
        return rows[store.id]
    if None in rows:
        return rows[None]
    return feature.default


def require(key, *, entity=None, store=None):
    if not is_enabled(key, entity=entity, store=store):
        feature = FEATURES_BY_KEY[key]
        entity_id = store.entity_id if store is not None else getattr(entity, 'id', entity)
        reason = _blocked_reason(feature, entity_id)
        if reason:
            raise PermissionDenied(gettext('{label}: {single_store_reason}').format(label=feature.label, single_store_reason=reason))
        if store is not None and feature.scope == ModuleRegistry.Scope.STORE:
            raise PermissionDenied(gettext(
                '{label} is switched off at {store}. An admin can switch it on under Settings > Features.',
            ).format(label=feature.label, store=store.name))
        raise PermissionDenied(gettext(
            '{label} is switched off. An admin can switch it on under Settings > Features.',
        ).format(label=feature.label))


class _FeatureGate(BasePermission):
    key = None

    def has_permission(self, request, view):
        entity_id = getattr(request.user, 'entity_id', None)
        if entity_id is not None:
            require(self.key, entity=entity_id)
        return True


def feature_enabled(key):
    """`permission_classes = [..., feature_enabled('analytics_dashboards')]`
    for an endpoint that belongs wholly to one firm-wide feature."""
    return type('_FeatureGate', (_FeatureGate,), {'key': key})


def feature_values(entity, store=None):
    """{key: bool} for every feature, as seen from `store` (or the firm as a
    whole when store is None, in which case a store-level feature counts as
    on if any store has it on)."""
    if entity is None:
        return {f.key: f.default for f in FEATURES}
    rows = {}
    for row in ModuleEnablement.objects.filter(module__key__in=FEATURES_BY_KEY, entity=entity).select_related('module'):
        rows.setdefault(row.module.key, {})[row.store_id] = row.enabled
    values = {}
    for feature in FEATURES:
        feature_rows = rows.get(feature.key, {})
        firm = feature_rows.get(None, feature.default)
        if unavailable_reason(feature.key, entity):
            values[feature.key] = False
        elif feature.scope != ModuleRegistry.Scope.STORE:
            values[feature.key] = firm
        elif store is not None:
            values[feature.key] = feature_rows.get(store.id, firm)
        else:
            store_ids = entity.stores.filter(is_active=True).values_list('id', flat=True)
            values[feature.key] = any(feature_rows.get(sid, firm) for sid in store_ids)
    return values


def set_feature(key, enabled, *, entity, store=None):
    feature = FEATURES_BY_KEY[key]
    module, _ = ModuleRegistry.objects.get_or_create(
        key=key, defaults={'name': feature.label, 'scope': feature.scope})
    ModuleEnablement.objects.update_or_create(
        module=module, entity=entity, store=store if feature.scope == ModuleRegistry.Scope.STORE else None,
        defaults={'enabled': enabled})
