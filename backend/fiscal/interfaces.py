"""Abstract fiscal-device interface. The deliberate architectural investment
called for in architecture.txt: POS and reporting code against FiscalDevice
only, so a future VFD (Virtual Fiscal Device) driver can be added as a
sibling of ManualEFDDriver without touching either.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FiscalSaleLine:
    description: str
    quantity: float
    unit_price: float
    vat_class: str  # exempt | zero_rated | standard


@dataclass
class FiscalSubmission:
    sale_id: str
    store_device_id: str
    lines: List[FiscalSaleLine] = field(default_factory=list)
    total: float = 0.0


@dataclass
class FiscalResult:
    success: bool
    receipt_number: Optional[str] = None
    error: Optional[str] = None
    retryable: bool = False
    # True when the device can't issue the receipt itself (a standalone EFD
    # machine): the sale is done and the cashier must enter the receipt
    # number printed by the machine — see fiscal.drivers.manual_efd.
    pending_manual: bool = False


class FiscalDevice(ABC):
    """What a fiscal driver must implement: submit a sale, get back a
    fiscal receipt number, and report device status. Errors are returned,
    not raised, so callers can drive the POS's printing/printed/failed
    -retry UI state without a try/except around every call site."""

    @abstractmethod
    def submit_sale(self, submission: FiscalSubmission) -> FiscalResult:
        raise NotImplementedError

    @abstractmethod
    def get_status(self) -> str:
        """'online' | 'offline' | 'error' | 'manual'."""
        raise NotImplementedError
