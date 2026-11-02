from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    name = 'notifications'

    def ready(self):
        from . import checks  # noqa: F401 — registers the SMS settings check
