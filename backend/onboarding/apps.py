from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    """A new shop's first steps (quick-add, the getting-started checklist,
    the demo shop). It composes several modules, so it sits above them:
    nothing else imports it."""
    name = 'onboarding'
