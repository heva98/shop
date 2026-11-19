"""A cache that lives for one HTTP request.

Every API call checks the caller's roles (core.permissions) and store
access (core.queryset_scoping) several times, and often a feature switch
(core.features) too: the permission class, the queryset and the serializer
each ask. The answers can't change halfway through a request unless the
request changes them itself, so they are read once and kept here.

Outside a request (management commands, tests calling a function
directly) there is no cache and every call reads the database, as before.
Saving or deleting a StoreRole or ModuleEnablement drops the cached
answers (see signals below), so a request that changes roles or features
sees its own change.
"""

from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

_cache = ContextVar('request_cache', default=None)


def cached(key, compute):
    """compute() once per request for `key`; uncached outside a request."""
    store = _cache.get()
    if store is None:
        return compute()
    if key not in store:
        store[key] = compute()
    return store[key]


def forget(prefix):
    """Drops every cached answer whose key starts with `prefix`."""
    store = _cache.get()
    if store:
        for key in [k for k in store if k[0] == prefix]:
            del store[key]


class RequestCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _cache.set({})
        try:
            return self.get_response(request)
        finally:
            _cache.reset(token)


def _connect():
    from .models import ModuleEnablement, StoreRole

    @receiver([post_save, post_delete], sender=StoreRole, weak=False)
    def _roles_changed(**kwargs):
        forget('store_roles')

    @receiver([post_save, post_delete], sender=ModuleEnablement, weak=False)
    def _features_changed(**kwargs):
        forget('feature_rows')
