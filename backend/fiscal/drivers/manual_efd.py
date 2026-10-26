"""Driver for a standalone TRA EFD machine that the system cannot talk to.

This is how most small shops already work: the cashier rings the sale
up on the EFD machine, which prints the fiscal receipt, and then types that
receipt's number back into the system. So this driver never issues a
receipt number itself — it reports the sale as awaiting manual entry, and
pos.Sale.record_fiscal_receipt() stores the number the cashier enters.

A real VFD integration (TRA's Virtual Fiscal Device API) becomes a sibling
driver implementing the same FiscalDevice interface, returning the TRA
receipt number directly instead of pending_manual.
"""

from fiscal.interfaces import FiscalDevice, FiscalResult, FiscalSubmission


class ManualEFDDriver(FiscalDevice):
    name = 'manual_efd'

    def __init__(self, device_id: str = ''):
        self.device_id = device_id

    def submit_sale(self, submission: FiscalSubmission) -> FiscalResult:
        return FiscalResult(
            success=False, pending_manual=True,
            error='Issue the receipt on the EFD machine, then enter its receipt number.',
        )

    def get_status(self) -> str:
        return 'manual'


def get_fiscal_driver(store):
    """The one place that decides which FiscalDevice a store uses. Every
    store is on a standalone EFD machine until a VFD driver exists."""
    return ManualEFDDriver(device_id=store.efd_device_id)
