"""Deployment checks for the kernel."""

from django.conf import settings
from django.core.checks import Warning, register


@register(deploy=True)
def database_check(app_configs, **kwargs):
    """`manage.py check --deploy` warns about SQLite in production. It is
    supported for one small shop (deploy/README.md), with writes taken one at
    a time (see DATABASES in settings), but Postgres is the stack the
    concurrency guarantees and analytics are designed for."""
    if settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
        return []
    return [Warning(
        'The database is SQLite. That suits one small shop; for several tills or branches set DATABASE_URL to Postgres.',
        hint='See deploy/README.md.', id='core.W001',
    )]
