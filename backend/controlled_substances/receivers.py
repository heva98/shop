"""Keeps the controlled drugs register as selling happens.

Selling announces every stock movement of a sale line (pos.events); this
module listens and enters controlled medicine in the register, so pos
never needs to know the register exists."""

from django.dispatch import receiver

from pos.events import sale_line_stock_moved

from .models import ControlledSubstanceEntry


@receiver(sale_line_stock_moved, dispatch_uid='controlled_substances.enter_sale_line')
def enter_sale_line(sender, *, sale, line, ledger_entry, user, prescription, returned, **kwargs):
    """One register row per controlled medicine dispensed, or returned to
    stock when its sale is voided, with who sold it and the prescription."""
    product = line.batch.product
    if not product.is_controlled_substance:
        return
    ControlledSubstanceEntry.objects.create(
        store=sale.store, product=product, ledger_entry=ledger_entry, sale=sale,
        kind=ControlledSubstanceEntry.Kind.RETURNED if returned else ControlledSubstanceEntry.Kind.DISPENSED,
        qty=-line.qty if returned else line.qty, batch_no=line.batch.batch_no,
        patient_name=prescription.patient_name, prescriber_name=prescription.prescriber_name,
        prescription_ref=prescription.prescription_ref, dispensed_by=user,
    )
