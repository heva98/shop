from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from core.errors import DomainError


def custom_exception_handler(exc, context):
    """Wraps DRF's default handler so business-rule refusals raised from
    the domain and service layers (every subclass of core.errors.DomainError)
    come back as a proper 400 with their message, not an unhandled 500,
    without every view having to catch them."""
    if isinstance(exc, DomainError):
        return Response({'detail': str(exc)}, status=400)
    return drf_exception_handler(exc, context)
