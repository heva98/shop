from django.conf import settings
from django.core.mail import send_mail

from notifications.interfaces import NotificationChannel


class EmailChannel(NotificationChannel):
    @property
    def configured(self):
        """False while mail only goes to the console (the dev default) —
        set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend and
        the EMAIL_HOST settings to really send."""
        return not any(dev in settings.EMAIL_BACKEND for dev in ('console', 'locmem', 'dummy'))

    def send(self, recipient: str, subject: str, body: str) -> bool:
        send_mail(subject, body, None, [recipient], fail_silently=False)
        return True
