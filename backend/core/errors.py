"""The one exception type the API layer needs to know about.

Each module refuses a request that breaks one of its business rules by
raising its own subclass of DomainError (SaleError, CreditError,
StockError, ...), with a message written for the person at the till.
config.exceptions maps every DomainError to HTTP 400, so a new module
gets that for free instead of adding itself to a list in the handler."""


class DomainError(Exception):
    """A business rule refused the request. The message is shown to the
    user as it is, so it must be translated and say what to do next."""
