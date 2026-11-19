from django.apps import AppConfig


class ControlledSubstancesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'controlled_substances'

    def ready(self):
        from . import receivers  # noqa: F401  (connects to pos.events)
