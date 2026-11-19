from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
        from .request_cache import _connect

        _connect()
