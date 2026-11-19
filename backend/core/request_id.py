"""One id per request, in every log line it writes and in the response's
X-Request-ID header. With several servers behind a load balancer, a
complaint ("the till said error at 10:42") can then be traced to the one
server and the exact log lines. nginx passes its own $request_id, so its
access log carries the same id; without one we make one up.
"""

import logging
import re
import uuid
from contextvars import ContextVar

from django.core.signals import request_finished

_request_id = ContextVar('request_id', default='-')
_SAFE = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def current():
    return _request_id.get()


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        given = request.headers.get('X-Request-ID', '')
        request_id = given if _SAFE.match(given) else uuid.uuid4().hex
        request.request_id = request_id
        # Cleared on request_finished, not here: Django logs a failed
        # request ("Internal Server Error: …") after the middleware returns.
        _request_id.set(request_id)
        response = self.get_response(request)
        response['X-Request-ID'] = request_id
        return response


def _clear(**kwargs):
    _request_id.set('-')


request_finished.connect(_clear, dispatch_uid='core.request_id.clear')


class RequestIdFilter(logging.Filter):
    """Adds %(request_id)s to every log record ('-' outside a request)."""

    def filter(self, record):
        record.request_id = _request_id.get()
        return True
