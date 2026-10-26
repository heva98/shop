"""Abstract PaymentMethod interface. Cash is the only active implementation
now; mobile_money and bank_transfer become sibling modules implementing the
same interface without changing POS or Transfer code, per architecture.txt.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class PaymentResult:
    success: bool
    reference: Optional[str] = None
    error: Optional[str] = None


class PaymentProcessor(ABC):
    @abstractmethod
    def charge(self, amount) -> PaymentResult:
        """Attempt to take payment for `amount`. Must not raise for
        recoverable failures — return PaymentResult(success=False, ...)."""
        raise NotImplementedError
