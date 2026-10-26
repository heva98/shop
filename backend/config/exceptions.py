from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from catalog.models import UnitConversionError
from credit.models import CreditError
from inventory.models import InsufficientStockError, StockError
from pos.models import SaleError


def custom_exception_handler(exc, context):
    """Wraps DRF's default handler so plain-Python business-rule exceptions
    raised from the model layer (not every view remembering to catch them)
    still come back as a proper 400, not an unhandled 500."""
    if isinstance(exc, (CreditError, InsufficientStockError, SaleError, StockError, UnitConversionError)):
        return Response({'detail': str(exc)}, status=400)
    return drf_exception_handler(exc, context)
