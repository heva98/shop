"""Sends heavy read-only work (reports, analytics) to a read replica, so a
month-long sales report never slows a checkout on the primary.

Opt-in per view, never by model: whether a read may be a second or two
stale depends on what the read is for, not on what table it touches. The
till's own reads (stock, prices, shift) always use the primary.

    @on_replica
    def sales(request): ...

With no DATABASE_REPLICA_URL configured this changes nothing, so the
same code runs on a single server. Writes always go to the primary.
"""

from contextvars import ContextVar
from functools import wraps

from django.conf import settings

REPLICA = 'replica'
_reading_from_replica = ContextVar('reading_from_replica', default=False)


def replica_configured():
    return REPLICA in settings.DATABASES


def on_replica(view):
    """Runs `view` (a read-only handler) with its reads on the replica."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _reading_from_replica.set(True)
        try:
            return view(*args, **kwargs)
        finally:
            _reading_from_replica.reset(token)
    return wrapper


class ReplicaRouter:
    def db_for_read(self, model, **hints):
        if _reading_from_replica.get() and replica_configured():
            return REPLICA
        return None  # the primary

    def db_for_write(self, model, **hints):
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        return True  # the replica is a copy of the primary: same rows

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        return db == 'default'  # the replica follows the primary by replication
