"""The Django admin's sign-in, with the same limits on wrong passwords as
the app (core.login_guard): without this, /admin/ was a place to guess
the platform administrator's password with no lockout at all.

(A second sign-in step for the platform administrator, a code from an
authenticator app, is planned; see the 2026-11 security audit, M2.)"""

from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm

from audit.services import Summary

from .login_guard import LockedOut, normalize_username, record_failure, refuse_if_locked


class GuardedAdminLogin(AdminAuthenticationForm):
    def clean(self):
        username = normalize_username(self.data.get('username', ''))
        if username:
            try:
                refuse_if_locked(self.request, username)
            except LockedOut as exc:
                raise forms.ValidationError(str(exc.detail), code='locked_out') from None
        try:
            return super().clean()
        except forms.ValidationError:
            if username and self.data.get('password') and self.user_cache is None:
                record_failure(self.request, username,
                               Summary('Wrong password for "{username}" at the admin site', username=username))
            raise


def secure_admin_site():
    """The default admin site with the guarded sign-in; for config.urls."""
    admin.site.login_form = GuardedAdminLogin
    return admin.site
