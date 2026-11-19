from core.errors import DomainError


class SaleError(DomainError):
    """A selling rule refused the request (wrong sale status, missing
    payment details, no shift open, ...). Mapped to HTTP 400 by
    config.exceptions.custom_exception_handler, like every DomainError."""
