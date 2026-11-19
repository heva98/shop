"""Getting a completed sale its tax (EFD) receipt, through whichever
fiscal.interfaces.FiscalDevice the store uses."""

from django.db import transaction
from django.utils.translation import gettext

from fiscal.drivers.manual_efd import get_fiscal_driver
from fiscal.interfaces import FiscalSaleLine, FiscalSubmission
from fiscal.models import FiscalReceipt

from ..errors import SaleError
from ..models import Sale


def _submission(sale):
    return FiscalSubmission(
        sale_id=str(sale.id),
        store_device_id=sale.store.efd_device_id,
        lines=[
            FiscalSaleLine(
                description=line.description, quantity=float(line.sell_qty),
                unit_price=float(line.amount / line.sell_qty) if line.sell_qty else float(line.unit_price),
                vat_class=line.vat_class,
            )
            for line in sale.lines.select_related('batch__product', 'sell_uom')
        ],
        total=float(sale.total),
    )


def fiscalize(sale):
    """Asks the store's fiscal driver for the sale's receipt — no stock
    movement — and returns its FiscalResult, so the till can show printed /
    failed / 'enter EFD receipt number'. Called on completion and by the
    till's 'Retry printing' button."""
    sale.require_status(Sale.Status.COMPLETED, 'fiscalize')
    driver = get_fiscal_driver(sale.store)
    result = driver.submit_sale(_submission(sale))
    if result.pending_manual:
        return result
    FiscalReceipt.objects.create(
        sale_id=sale.id, driver=driver.name,
        receipt_number=result.receipt_number or '',
        status=FiscalReceipt.Status.SUBMITTED if result.success else FiscalReceipt.Status.FAILED,
        error=result.error or '',
    )
    if result.success:
        sale.efd_receipt_no = result.receipt_number
        sale.save(update_fields=['efd_receipt_no'])
    return result


@transaction.atomic
def record_receipt(sale, *, receipt_number, user):
    """Stores the receipt number printed by a standalone EFD machine."""
    receipt_number = (receipt_number or '').strip()
    if not receipt_number:
        raise SaleError(gettext('Enter the EFD receipt number.'))
    if sale.status == Sale.Status.OPEN:
        raise SaleError(gettext('Complete the sale before recording its EFD receipt.'))
    if sale.efd_receipt_no:
        raise SaleError(gettext('EFD receipt {efd_receipt_no} is already recorded for this sale.').format(efd_receipt_no=sale.efd_receipt_no))
    if Sale.objects.filter(store=sale.store, efd_receipt_no=receipt_number).exclude(pk=sale.pk).exists():
        raise SaleError(gettext('EFD receipt {receipt_number} is already recorded on another sale. Check the number.').format(receipt_number=receipt_number))
    FiscalReceipt.objects.create(
        sale_id=sale.id, driver=get_fiscal_driver(sale.store).name, receipt_number=receipt_number,
        status=FiscalReceipt.Status.RECORDED, entered_by=user,
    )
    sale.efd_receipt_no = receipt_number
    sale.save(update_fields=['efd_receipt_no'])
