"""The on/off switches for each notification channel (Settings >
Notifications), stored as core.ModuleEnablement rows."""

from django.db.models import Q

from core.models import ModuleEnablement

from .models import NotificationLog

MODULE_KEY_BY_CHANNEL = {
    NotificationLog.Channel.EMAIL: 'email_notifier',
    NotificationLog.Channel.SMS: 'sms_notifier',
}


def channel_enabled(channel_key, store):
    return ModuleEnablement.objects.filter(
        module__key=MODULE_KEY_BY_CHANNEL[channel_key], entity=store.entity, enabled=True,
    ).filter(Q(store=store) | Q(store__isnull=True)).exists()


def sms_enabled(store):
    return channel_enabled(NotificationLog.Channel.SMS, store)
