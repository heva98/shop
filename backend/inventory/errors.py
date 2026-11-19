from core.errors import DomainError


class InsufficientStockError(DomainError):
    """A requested stock movement would take a batch below zero, or there
    isn't enough total stock across batches to cover an allocation. Mapped
    to an HTTP 400 by config.exceptions.custom_exception_handler — never
    silently clamped, since that would mean selling stock that isn't
    there."""


class StockError(DomainError):
    """A stock operation broke a business rule (receiving a perishable
    line without an expiry date, approving a count twice, ...). Mapped to
    HTTP 400 by config.exceptions.custom_exception_handler."""
