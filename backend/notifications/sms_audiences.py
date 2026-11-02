"""Who gets which SMS: one Recipient per (person, store), with the values
their template needs. The checks and sending are sms_service's job."""

from django.utils import translation
from django.utils.translation import gettext

from core.models import Role, User
from reports.views import summarize_day

from .models import SmsConfiguration, SmsMessage
from .modules import sms_enabled
from .sms_service import Recipient
from .sms_templates import DAILY_SALES_SUMMARY


def owners(entity):
    """The shop's owners: entity admins (shown as "Owner" in the app)."""
    return User.objects.filter(
        entity=entity, is_active=True, store_roles__store__isnull=True, store_roles__role=Role.ENTITY_ADMIN,
    ).distinct()


def store_managers(store):
    return User.objects.filter(
        is_active=True, store_roles__store=store, store_roles__role=Role.STORE_MANAGER,
    ).distinct()


def daily_sales_values(entity, store, day, stats):
    """Template values for DAILY_SALES_SUMMARY, in the active language."""
    by_method = ', '.join(f'{gettext(name)} {total:,.0f}' for name, total in stats['by_method'])
    return {
        'shop': entity.name,
        'store': store.name,
        'date': f'{day:%d/%m}',
        'sales_total': f"{stats['sales_total']:,.0f}",
        'sales_count': str(stats['sales_count']),
        'by_method': by_method or '-',
        'voids': str(stats['void_count']),
        'missing_efd': str(stats['missing_efd']),
        'cash_diff': f"{stats['variance']:+,.0f}",
        'purchases': f"{stats['purchases_total']:,.0f}",
        'low_stock': str(stats['low_stock']),
        'expiring': str(stats['expiring']),
    }


def daily_sales_recipients(entity, day, language=None):
    """The owners (and, if switched on, each store's managers) for every
    active store with SMS switched on — one message per person per store."""
    config = SmsConfiguration.load(entity)
    shop_owners = list(owners(entity))
    recipients = []
    for store in entity.stores.filter(is_active=True).order_by('name'):
        if not sms_enabled(store):
            continue
        people = list(shop_owners)
        if config.daily_sales_to_managers:
            people += [m for m in store_managers(store) if m not in people]
        if not people:
            continue
        stats = summarize_day(store, day)
        for user in people:
            lang = language or config.language or user.language or 'sw'
            with translation.override(lang):
                values = daily_sales_values(entity, store, day, stats)
            recipients.append(Recipient(
                phone=user.phone, template_key=DAILY_SALES_SUMMARY, language=lang, values=values,
                user=user, name=user.get_full_name() or user.username, store=store,
                skip_reason='' if user.phone else SmsMessage.SkipReason.NO_PHONE,
            ))
    return recipients
